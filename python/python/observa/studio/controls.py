"""Native Codex settings and decisions. Studio never implements automatic review."""
from __future__ import annotations

PERMISSIONS = {
    "cautious": dict(label="Ask before commands", policy="untrusted", reviewer="user", sandbox="workspace-write",
                     description="Review commands outside Codex's trusted set. Project write sandbox."),
    "default": dict(label="Ask when needed", policy="on-request", reviewer="user", sandbox="workspace-write",
                    description="Routine project edits and commands run automatically; broader access asks you."),
    "automatic": dict(label="Approve for me", policy="on-request", reviewer="auto_review", sandbox="workspace-write",
                      description="Codex's native automatic reviewer handles eligible approval requests."),
    "read-only": dict(label="Read only", policy="on-request", reviewer="user", sandbox="read-only",
                      description="Inspect files; writes and broader actions require approval."),
    "sandboxed": dict(label="Automatic within sandbox", policy="never", reviewer="user", sandbox="workspace-write",
                      description="Run within the project sandbox without prompts; actions outside it are denied."),
    "full-access": dict(label="Full access", policy="never", reviewer="user", sandbox="danger-full-access",
                        description="Unrestricted filesystem and network access without command approval. Only enable for trusted work."),
}


def permission_options(requirements: dict) -> list[dict]:
    choices = []
    for identifier, preset in PERMISSIONS.items():
        reason = None
        for key, value in (("allowedApprovalPolicies", preset["policy"]),
                           ("allowedApprovalsReviewers", preset["reviewer"]),
                           ("allowedSandboxModes", preset["sandbox"])):
            allowed = requirements.get(key)
            if allowed is not None and value not in allowed:
                reason = "Restricted by your Codex requirements."
        if identifier == "automatic" and (requirements.get("featureRequirements") or {}).get("guardian_approval") is False:
            reason = "Automatic review is disabled by your Codex requirements."
        choices.append({"id": identifier, **preset, "disabled_reason": reason})
    return choices


def validate_settings(value: dict, options: dict) -> dict:
    if set(value) - {"model", "effort", "mode", "permissions", "confirm_full_access"}:
        raise ValueError("Unknown Codex setting.")
    model = next((m for m in options["models"] if m["model"] == value.get("model")), None)
    if not model:
        raise ValueError("Select a model returned by your installed Codex.")
    effort = value.get("effort") or model["defaultReasoningEffort"]
    if effort not in [e["reasoningEffort"] for e in model["supportedReasoningEfforts"]]:
        raise ValueError("This reasoning effort is not supported by the selected model.")
    mode = value.get("mode", "default")
    if mode not in [m["mode"] for m in options["modes"]]:
        raise ValueError("This mode is not available from your installed Codex.")
    permission = value.get("permissions", "cautious")
    choice = next((p for p in options["permissions"] if p["id"] == permission), None)
    if not choice or choice["disabled_reason"]:
        raise ValueError("These permissions are not allowed by your Codex configuration.")
    if permission == "full-access" and value.get("confirm_full_access") is not True:
        raise ValueError("Explicitly confirm unrestricted filesystem and network access.")
    return dict(model=model["model"], effort=effort, mode=mode, permissions=permission)


def approval_choices(method: str, params: dict) -> list[dict]:
    if method == "item/permissions/requestApproval":
        return [dict(label="Allow this turn", decision="accept", scope="turn"),
                dict(label="Allow for session", decision="accept", scope="session"),
                dict(label="Decline", decision="decline", scope="turn")]
    if method not in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return []
    decisions = params.get("availableDecisions")
    if decisions is None:
        decisions = ["accept", "acceptForSession", "decline", "cancel"]
        if method == "item/commandExecution/requestApproval":
            if params.get("proposedExecpolicyAmendment"):
                decisions.append({"acceptWithExecpolicyAmendment": {"execpolicy_amendment": params["proposedExecpolicyAmendment"]}})
            for amendment in params.get("proposedNetworkPolicyAmendments") or []:
                decisions.append({"applyNetworkPolicyAmendment": {"network_policy_amendment": amendment}})
    labels = {"accept": "Allow once", "acceptForSession": "Allow for session", "decline": "Decline", "cancel": "Cancel turn"}
    choices = []
    for decision in decisions:
        if isinstance(decision, str) and decision in labels:
            choices.append(dict(label=labels[decision], decision=decision))
        elif isinstance(decision, dict) and "acceptWithExecpolicyAmendment" in decision:
            choices.append(dict(label="Allow matching commands (save rule)", decision=decision))
        elif isinstance(decision, dict) and "applyNetworkPolicyAmendment" in decision:
            choices.append(dict(label="Apply proposed network rule", decision=decision))
    return choices
