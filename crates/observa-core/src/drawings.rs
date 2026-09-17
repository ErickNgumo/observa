//! Strategy annotations ("drawings") — OBS-AI-02.
//!
//! Drawings are **descriptive only**. They are recorded in the canonical run
//! history (`drawings_emitted` events) and rendered by replay; they never
//! influence order creation, fills, spread/slippage, SL/TP, margin, portfolio
//! accounting, metrics or execution chronology.
//!
//! The model is deliberately small and generic: a [`DrawingInstruction`] has a
//! stable `id`, an `action` and one optional typed kind. Strategies describe
//! *what to draw*; Observa never interprets strategy concepts such as "FVG" or
//! "POC".
//!
//! Parsing is strict: [`DrawingRegistry::parse_bar`] validates a bar's raw
//! instructions (as `serde_json::Value`, which is how both the shipped Python
//! binding and the dev bridge hand them over) and returns a [`DrawingError`]
//! with a stable machine-readable `code` instead of silently defaulting.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Maximum number of drawing instructions accepted for a single bar.
///
/// Guards the canonical event log and the replay payload against runaway
/// strategies. Exceeding it fails the run with `DRAWING_LIMIT_EXCEEDED`.
pub const MAX_DRAWINGS_PER_BAR: usize = 256;

// ────────────────────────────────────────────────
// Enums
// ────────────────────────────────────────────────

/// What to do with a drawing instruction.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DrawingAction {
    /// Create the drawing, or append the current bar's point for a series.
    Add,
    /// Replace the current spec of an existing drawing (same id, same type).
    Update,
    /// Remove the drawing (and, for a series, stop the series).
    Remove,
}

impl Default for DrawingAction {
    fn default() -> Self {
        DrawingAction::Add
    }
}

/// Stroke style for lines and series.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LineStyle {
    Solid,
    Dashed,
    Dotted,
}

impl Default for LineStyle {
    fn default() -> Self {
        LineStyle::Solid
    }
}

/// How a continuous series is rendered.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SeriesKind {
    Line,
    Histogram,
}

impl Default for SeriesKind {
    fn default() -> Self {
        SeriesKind::Line
    }
}

/// Which pane a series is drawn in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DrawingPane {
    /// Overlay on the price (candle) chart.
    Price,
    /// The single generic secondary strategy pane.
    Separate,
}

impl Default for DrawingPane {
    fn default() -> Self {
        DrawingPane::Price
    }
}

/// Marker placement relative to its bar.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MarkerPosition {
    Above,
    Below,
}

impl Default for MarkerPosition {
    fn default() -> Self {
        MarkerPosition::Below
    }
}

/// Marker glyph.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MarkerShape {
    Circle,
    Square,
    ArrowUp,
    ArrowDown,
}

impl Default for MarkerShape {
    fn default() -> Self {
        MarkerShape::Circle
    }
}

/// Label placement relative to its anchor point.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LabelPosition {
    Above,
    Below,
    Left,
    Right,
}

impl Default for LabelPosition {
    fn default() -> Self {
        LabelPosition::Above
    }
}

// ────────────────────────────────────────────────
// Drawing kinds
// ────────────────────────────────────────────────

/// A continuous per-bar series (EMA, VWAP, z-score, spread, RSI-like values).
///
/// One instruction is emitted per bar with the same `id`; the renderer
/// accumulates the points into a single line/histogram series. `value: null`
/// (or simply not emitting) is a gap — never zero, never interpolated.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SeriesDrawing {
    /// Current bar's value; `None` represents a gap.
    pub value: Option<f64>,
    /// `line` (default) or `histogram`.
    #[serde(default)]
    pub series_type: SeriesKind,
    /// Stroke style.
    #[serde(default)]
    pub line_style: LineStyle,
    /// Stroke width: 1, 2 or 3.
    #[serde(default = "default_width")]
    pub width: u32,
    /// Stroke/fill colour (`#RRGGBB` or `#RRGGBBAA`).
    pub color: String,
    /// `price` (default) or `separate`.
    #[serde(default)]
    pub pane: DrawingPane,
    /// Legend label (falls back to `id`).
    pub label: Option<String>,
}

/// A horizontal price level (POC/VAH/VAL, support/resistance, key prices).
///
/// Naturally extended across the chart — strategies do not re-emit it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HLineDrawing {
    pub price: f64,
    pub color: String,
    #[serde(default)]
    pub line_style: LineStyle,
    #[serde(default = "default_width")]
    pub width: u32,
    pub label: Option<String>,
}

/// A straight line between two points. Both endpoints are required.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LineDrawing {
    pub x1: String,
    pub y1: f64,
    pub x2: String,
    pub y2: f64,
    pub color: String,
    #[serde(default)]
    pub line_style: LineStyle,
    #[serde(default = "default_width")]
    pub width: u32,
}

/// A price zone (FVG, order block, value area, supply/demand).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RectangleDrawing {
    pub time_start: String,
    /// `None` extends the zone to the right as replay advances.
    pub time_end: Option<String>,
    pub price_top: f64,
    pub price_bot: f64,
    pub color: String,
    /// Fill opacity in `0..=1`.
    pub opacity: Option<f64>,
    pub border: Option<String>,
    pub label: Option<String>,
}

/// A time-window region (session, news window, research window). No price
/// semantics.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RegionDrawing {
    pub time_start: String,
    pub time_end: String,
    pub color: String,
    /// Fill opacity in `0..=1`.
    pub opacity: Option<f64>,
    pub label: Option<String>,
}

/// A strategy marker anchored to a bar (signal fired, rejected signal,
/// anomaly).
///
/// These are **strategy** annotations and are kept separate from the canonical
/// execution markers Observa derives from `position_opened`/`position_closed`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MarkerDrawing {
    pub time: String,
    #[serde(default)]
    pub position: MarkerPosition,
    #[serde(default)]
    pub shape: MarkerShape,
    pub color: String,
    pub text: Option<String>,
}

/// A text label anchored at a price and time.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LabelDrawing {
    pub time: String,
    pub price: f64,
    pub text: String,
    pub color: String,
    #[serde(default)]
    pub position: LabelPosition,
}

/// Legacy per-bar colour override.
///
/// Accepted only for backward compatibility; it is **not** part of the
/// OBS-AI-02 public contract and receives no new functionality.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BarColorDrawing {
    pub time: String,
    pub color: String,
}

/// The typed drawing payload.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DrawingKind {
    Series(SeriesDrawing),
    Hline(HLineDrawing),
    Line(LineDrawing),
    Rectangle(RectangleDrawing),
    Region(RegionDrawing),
    Marker(MarkerDrawing),
    Label(LabelDrawing),
    BarColor(BarColorDrawing),
}

impl DrawingKind {
    /// Stable type tag used in validation errors and registry bookkeeping.
    pub fn tag(&self) -> &'static str {
        match self {
            DrawingKind::Series(_) => "series",
            DrawingKind::Hline(_) => "hline",
            DrawingKind::Line(_) => "line",
            DrawingKind::Rectangle(_) => "rectangle",
            DrawingKind::Region(_) => "region",
            DrawingKind::Marker(_) => "marker",
            DrawingKind::Label(_) => "label",
            DrawingKind::BarColor(_) => "bar_color",
        }
    }

    /// Timestamps referenced by this drawing, as emitted (RFC 3339 strings).
    pub fn timestamps(&self) -> Vec<(&'static str, &str)> {
        match self {
            DrawingKind::Series(_) | DrawingKind::Hline(_) => Vec::new(),
            DrawingKind::Line(l) => vec![("x1", l.x1.as_str()), ("x2", l.x2.as_str())],
            DrawingKind::Rectangle(r) => {
                let mut out = vec![("time_start", r.time_start.as_str())];
                if let Some(end) = r.time_end.as_deref() {
                    out.push(("time_end", end));
                }
                out
            }
            DrawingKind::Region(r) => vec![
                ("time_start", r.time_start.as_str()),
                ("time_end", r.time_end.as_str()),
            ],
            DrawingKind::Marker(m) => vec![("time", m.time.as_str())],
            DrawingKind::Label(l) => vec![("time", l.time.as_str())],
            DrawingKind::BarColor(b) => vec![("time", b.time.as_str())],
        }
    }
}

/// A single drawing instruction from a strategy.
///
/// `kind` is `None` only for `action: "remove"`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DrawingInstruction {
    /// Stable strategy-assigned id (`^[A-Za-z0-9_.:-]{1,64}$`).
    pub id: String,
    /// What to do with this drawing (defaults to `add`).
    #[serde(default)]
    pub action: DrawingAction,
    /// The drawing itself; absent for `remove`.
    #[serde(flatten)]
    pub kind: Option<DrawingKind>,
}

fn default_width() -> u32 {
    1
}

// ────────────────────────────────────────────────
// Validation
// ────────────────────────────────────────────────

/// A structured drawing-validation failure.
///
/// `code` is the stable machine-readable contract; `details` carries only
/// values the validator actually knows (never parsed out of the message).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DrawingError {
    pub code: String,
    pub message: String,
    pub details: Value,
}

impl DrawingError {
    fn new(code: &str, message: impl Into<String>, details: Value) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            details,
        }
    }
}

/// Per-run registry of live drawing ids, used for lifecycle validation.
#[derive(Debug, Default, Clone)]
pub struct DrawingRegistry {
    ids: BTreeMap<String, String>,
}

impl DrawingRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Ids currently defined (test/diagnostic support).
    pub fn live_ids(&self) -> Vec<&str> {
        self.ids.keys().map(|k| k.as_str()).collect()
    }

    /// Parses and validates one bar's raw instructions, applying lifecycle
    /// rules (add/update/remove) to the registry.
    pub fn parse_bar(
        &mut self,
        values: &[Value],
        bar_index: usize,
    ) -> Result<Vec<DrawingInstruction>, DrawingError> {
        if values.len() > MAX_DRAWINGS_PER_BAR {
            return Err(DrawingError::new(
                "DRAWING_LIMIT_EXCEEDED",
                format!(
                    "bar {bar_index} returned {} drawing instructions; the maximum is {MAX_DRAWINGS_PER_BAR}",
                    values.len()
                ),
                json!({ "bar_index": bar_index, "count": values.len(), "limit": MAX_DRAWINGS_PER_BAR }),
            ));
        }

        let mut parsed = Vec::with_capacity(values.len());
        for (index, value) in values.iter().enumerate() {
            let instruction = parse_instruction(value, index, bar_index)?;
            self.apply_lifecycle(&instruction, index, bar_index)?;
            parsed.push(instruction);
        }
        Ok(parsed)
    }

    fn apply_lifecycle(
        &mut self,
        instruction: &DrawingInstruction,
        index: usize,
        bar_index: usize,
    ) -> Result<(), DrawingError> {
        let ctx = |extra: Value| -> Value {
            let mut base = json!({
                "index": index,
                "bar_index": bar_index,
                "drawing_id": instruction.id,
            });
            if let (Some(map), Some(extra_map)) = (base.as_object_mut(), extra.as_object()) {
                for (k, v) in extra_map {
                    map.insert(k.clone(), v.clone());
                }
            }
            base
        };

        match instruction.action {
            DrawingAction::Add => {
                let kind = instruction.kind.as_ref().expect("add carries a kind");
                match self.ids.get(&instruction.id) {
                    Some(existing) if existing == kind.tag() => Ok(()),
                    Some(existing) => Err(DrawingError::new(
                        "DRAWING_ACTION_INVALID",
                        format!(
                            "drawing '{}' already exists as '{}'; cannot add it as '{}'",
                            instruction.id,
                            existing,
                            kind.tag()
                        ),
                        ctx(json!({ "action": "add", "existing_type": existing, "drawing_type": kind.tag() })),
                    )),
                    None => {
                        self.ids
                            .insert(instruction.id.clone(), kind.tag().to_string());
                        Ok(())
                    }
                }
            }
            DrawingAction::Update => {
                let kind = instruction.kind.as_ref().expect("update carries a kind");
                if kind.tag() == "series" {
                    return Err(DrawingError::new(
                        "DRAWING_ACTION_INVALID",
                        format!(
                            "drawing '{}' is a series; series points are appended with action 'add' and cannot be updated",
                            instruction.id
                        ),
                        ctx(json!({ "action": "update", "drawing_type": "series" })),
                    ));
                }
                match self.ids.get(&instruction.id) {
                    None => Err(DrawingError::new(
                        "DRAWING_REFERENCE_INVALID",
                        format!(
                            "drawing '{}' cannot be updated because it does not exist",
                            instruction.id
                        ),
                        ctx(json!({ "action": "update", "drawing_type": kind.tag() })),
                    )),
                    Some(existing) if existing != kind.tag() => Err(DrawingError::new(
                        "DRAWING_ACTION_INVALID",
                        format!(
                            "drawing '{}' is '{}'; update must keep the same type, got '{}'",
                            instruction.id,
                            existing,
                            kind.tag()
                        ),
                        ctx(json!({ "action": "update", "existing_type": existing, "drawing_type": kind.tag() })),
                    )),
                    Some(_) => Ok(()),
                }
            }
            DrawingAction::Remove => match self.ids.remove(&instruction.id) {
                Some(_) => Ok(()),
                None => Err(DrawingError::new(
                    "DRAWING_REFERENCE_INVALID",
                    format!(
                        "drawing '{}' cannot be removed because it does not exist",
                        instruction.id
                    ),
                    ctx(json!({ "action": "remove" })),
                )),
            },
        }
    }
}

/// Validates an id against `^[A-Za-z0-9_.:-]{1,64}$`.
pub fn id_is_valid(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | ':' | '-'))
}

fn invalid_value(
    field: &str,
    value: &Value,
    expected: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> DrawingError {
    DrawingError::new(
        "DRAWING_VALUE_INVALID",
        format!("drawing {id}: field '{field}' {expected} (got {value})"),
        json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "field": field, "value": value }),
    )
}

fn missing_field(
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
    drawing_type: &Value,
) -> DrawingError {
    DrawingError::new(
        "DRAWING_FIELD_MISSING",
        format!("drawing {id} ({drawing_type}): required field '{field}' is missing"),
        json!({
            "index": index,
            "bar_index": bar_index,
            "drawing_id": id,
            "drawing_type": drawing_type,
            "field": field,
        }),
    )
}

fn req_str(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
    drawing_type: &Value,
) -> Result<String, DrawingError> {
    match map.get(field) {
        None | Some(Value::Null) => Err(missing_field(field, index, bar_index, id, drawing_type)),
        Some(Value::String(s)) => Ok(s.clone()),
        Some(other) => Err(invalid_value(field, other, "must be a string", index, bar_index, id)),
    }
}

fn req_f64(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
    drawing_type: &Value,
) -> Result<f64, DrawingError> {
    match map.get(field) {
        None | Some(Value::Null) => Err(missing_field(field, index, bar_index, id, drawing_type)),
        Some(Value::Number(n)) => {
            let v = n.as_f64().ok_or_else(|| {
                invalid_value(
                    field,
                    &Value::Number(n.clone()),
                    "must be a finite number",
                    index,
                    bar_index,
                    id,
                )
            })?;
            if v.is_finite() {
                Ok(v)
            } else {
                Err(invalid_value(
                    field,
                    &Value::Number(n.clone()),
                    "must be finite",
                    index,
                    bar_index,
                    id,
                ))
            }
        }
        Some(other) => Err(invalid_value(field, other, "must be a number", index, bar_index, id)),
    }
}

fn opt_f64(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<Option<f64>, DrawingError> {
    match map.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => {
            let v = n.as_f64().ok_or_else(|| {
                invalid_value(
                    field,
                    &Value::Number(n.clone()),
                    "must be a finite number",
                    index,
                    bar_index,
                    id,
                )
            })?;
            if v.is_finite() {
                Ok(Some(v))
            } else {
                Err(invalid_value(
                    field,
                    &Value::Number(n.clone()),
                    "must be finite",
                    index,
                    bar_index,
                    id,
                ))
            }
        }
        Some(other) => Err(invalid_value(field, other, "must be a number", index, bar_index, id)),
    }
}

fn opt_str(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<Option<String>, DrawingError> {
    match map.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.clone())),
        Some(other) => Err(invalid_value(field, other, "must be a string", index, bar_index, id)),
    }
}

fn req_color(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
    drawing_type: &Value,
) -> Result<String, DrawingError> {
    let raw = req_str(map, field, index, bar_index, id, drawing_type)?;
    if is_valid_color(&raw) {
        Ok(raw)
    } else {
        Err(invalid_value(
            field,
            &Value::String(raw),
            "must be a hex colour '#RRGGBB' or '#RRGGBBAA'",
            index,
            bar_index,
            id,
        ))
    }
}

fn opt_color(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<Option<String>, DrawingError> {
    match opt_str(map, field, index, bar_index, id)? {
        None => Ok(None),
        Some(raw) if is_valid_color(&raw) => Ok(Some(raw)),
        Some(raw) => Err(invalid_value(
            field,
            &Value::String(raw),
            "must be a hex colour '#RRGGBB' or '#RRGGBBAA'",
            index,
            bar_index,
            id,
        )),
    }
}

/// `#RRGGBB` or `#RRGGBBAA`.
pub fn is_valid_color(color: &str) -> bool {
    let bytes = color.as_bytes();
    (bytes.len() == 7 || bytes.len() == 9)
        && bytes[0] == b'#'
        && bytes[1..].iter().all(|b| b.is_ascii_hexdigit())
}

fn opt_opacity(
    map: &serde_json::Map<String, Value>,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<Option<f64>, DrawingError> {
    match opt_f64(map, "opacity", index, bar_index, id)? {
        None => Ok(None),
        Some(v) if (0.0..=1.0).contains(&v) => Ok(Some(v)),
        Some(v) => Err(invalid_value(
            "opacity",
            &json!(v),
            "must be between 0 and 1",
            index,
            bar_index,
            id,
        )),
    }
}

fn opt_width(
    map: &serde_json::Map<String, Value>,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<u32, DrawingError> {
    match map.get("width") {
        None | Some(Value::Null) => Ok(1),
        Some(Value::Number(n)) => match n.as_u64() {
            Some(w @ 1..=3) => Ok(w as u32),
            _ => Err(invalid_value(
                "width",
                &Value::Number(n.clone()),
                "must be 1, 2 or 3",
                index,
                bar_index,
                id,
            )),
        },
        Some(other) => Err(invalid_value("width", other, "must be 1, 2 or 3", index, bar_index, id)),
    }
}

/// `line_style` (canonical) with the legacy `style` key accepted as a
/// deprecated alias.
fn opt_line_style(
    map: &serde_json::Map<String, Value>,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<LineStyle, DrawingError> {
    let raw = match map.get("line_style") {
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Null) | None => opt_str(map, "style", index, bar_index, id)?,
        Some(other) => {
            return Err(invalid_value(
                "line_style",
                other,
                "must be a string",
                index,
                bar_index,
                id,
            ))
        }
    };
    match raw.as_deref() {
        None => Ok(LineStyle::Solid),
        Some("solid") => Ok(LineStyle::Solid),
        Some("dashed") => Ok(LineStyle::Dashed),
        Some("dotted") => Ok(LineStyle::Dotted),
        Some(other) => Err(invalid_value(
            "line_style",
            &Value::String(other.to_string()),
            "must be 'solid', 'dashed' or 'dotted'",
            index,
            bar_index,
            id,
        )),
    }
}

fn req_time(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
    drawing_type: &Value,
) -> Result<String, DrawingError> {
    let raw = req_str(map, field, index, bar_index, id, drawing_type)?;
    if parse_timestamp(&raw).is_some() {
        Ok(raw)
    } else {
        Err(DrawingError::new(
            "DRAWING_TIME_INVALID",
            format!("drawing {id}: field '{field}' is not a valid timestamp: {raw}"),
            json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "field": field, "value": raw }),
        ))
    }
}

fn opt_time(
    map: &serde_json::Map<String, Value>,
    field: &str,
    index: usize,
    bar_index: usize,
    id: &Value,
) -> Result<Option<String>, DrawingError> {
    match opt_str(map, field, index, bar_index, id)? {
        None => Ok(None),
        Some(raw) => {
            if parse_timestamp(&raw).is_some() {
                Ok(Some(raw))
            } else {
                Err(DrawingError::new(
                    "DRAWING_TIME_INVALID",
                    format!("drawing {id}: field '{field}' is not a valid timestamp: {raw}"),
                    json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "field": field, "value": raw }),
                ))
            }
        }
    }
}

/// Accepts RFC 3339 (`2024-01-01T00:00:00+00:00`) and the CSV form
/// (`2024-01-01 00:00:00+00:00`).
pub fn parse_timestamp(value: &str) -> Option<chrono::DateTime<chrono::FixedOffset>> {
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(value) {
        return Some(dt);
    }
    chrono::DateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%:z").ok()
}

fn parse_instruction(
    value: &Value,
    index: usize,
    bar_index: usize,
) -> Result<DrawingInstruction, DrawingError> {
    let map = match value {
        Value::Object(map) => map,
        other => {
            return Err(DrawingError::new(
                "DRAWING_TYPE_INVALID",
                format!("drawing #{index} must be a mapping, got {other}"),
                json!({ "index": index, "bar_index": bar_index }),
            ))
        }
    };

    let id_value = map.get("id").cloned().unwrap_or(Value::Null);
    let id = match map.get("id") {
        Some(Value::String(s)) if id_is_valid(s) => s.clone(),
        Some(Value::String(s)) => {
            return Err(DrawingError::new(
                "DRAWING_ID_INVALID",
                format!("drawing id '{s}' is invalid; expected ^[A-Za-z0-9_.:-]{{1,64}}$"),
                json!({ "index": index, "bar_index": bar_index, "drawing_id": s }),
            ))
        }
        Some(other) => {
            return Err(DrawingError::new(
                "DRAWING_ID_INVALID",
                format!("drawing id must be a string, got {other}"),
                json!({ "index": index, "bar_index": bar_index }),
            ))
        }
        None => {
            return Err(DrawingError::new(
                "DRAWING_ID_INVALID",
                format!("drawing #{index} is missing a required 'id'"),
                json!({ "index": index, "bar_index": bar_index }),
            ))
        }
    };

    let action = match map.get("action") {
        None | Some(Value::Null) => DrawingAction::Add,
        Some(Value::String(s)) => match s.as_str() {
            "add" => DrawingAction::Add,
            "update" => DrawingAction::Update,
            "remove" => DrawingAction::Remove,
            other => {
                return Err(DrawingError::new(
                    "DRAWING_ACTION_INVALID",
                    format!("drawing '{id}': unknown action '{other}' (expected add, update or remove)"),
                    json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "action": other }),
                ))
            }
        },
        Some(other) => {
            return Err(DrawingError::new(
                "DRAWING_ACTION_INVALID",
                format!("drawing '{id}': action must be a string, got {other}"),
                json!({ "index": index, "bar_index": bar_index, "drawing_id": id }),
            ))
        }
    };

    if action == DrawingAction::Remove {
        return Ok(DrawingInstruction {
            id,
            action,
            kind: None,
        });
    }

    let type_value = map.get("type").cloned().unwrap_or(Value::Null);
    let drawing_type = match map.get("type") {
        Some(Value::String(s)) => s.clone(),
        _ => {
            return Err(DrawingError::new(
                "DRAWING_TYPE_INVALID",
                format!("drawing '{id}' is missing a required 'type'"),
                json!({ "index": index, "bar_index": bar_index, "drawing_id": id }),
            ))
        }
    };

    let id_ref = &id_value;
    let type_ref = &type_value;

    let kind = match drawing_type.as_str() {
        "series" => DrawingKind::Series(SeriesDrawing {
            value: opt_f64(map, "value", index, bar_index, id_ref)?,
            series_type: match map.get("series_type") {
                None | Some(Value::Null) => SeriesKind::Line,
                Some(Value::String(s)) => match s.as_str() {
                    "line" => SeriesKind::Line,
                    "histogram" => SeriesKind::Histogram,
                    other => {
                        return Err(invalid_value(
                            "series_type",
                            &Value::String(other.to_string()),
                            "must be 'line' or 'histogram'",
                            index,
                            bar_index,
                            id_ref,
                        ))
                    }
                },
                Some(other) => {
                    return Err(invalid_value(
                        "series_type",
                        other,
                        "must be a string",
                        index,
                        bar_index,
                        id_ref,
                    ))
                }
            },
            line_style: opt_line_style(map, index, bar_index, id_ref)?,
            width: opt_width(map, index, bar_index, id_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            pane: match map.get("pane") {
                None | Some(Value::Null) => DrawingPane::Price,
                Some(Value::String(s)) => match s.as_str() {
                    "price" => DrawingPane::Price,
                    "separate" => DrawingPane::Separate,
                    other => {
                        return Err(DrawingError::new(
                            "DRAWING_PANE_INVALID",
                            format!("drawing '{id}': pane must be 'price' or 'separate', got '{other}'"),
                            json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "field": "pane", "value": other }),
                        ))
                    }
                },
                Some(other) => {
                    return Err(DrawingError::new(
                        "DRAWING_PANE_INVALID",
                        format!("drawing '{id}': pane must be 'price' or 'separate', got {other}"),
                        json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "field": "pane" }),
                    ))
                }
            },
            label: opt_str(map, "label", index, bar_index, id_ref)?,
        }),
        "hline" => DrawingKind::Hline(HLineDrawing {
            price: req_f64(map, "price", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            line_style: opt_line_style(map, index, bar_index, id_ref)?,
            width: opt_width(map, index, bar_index, id_ref)?,
            label: opt_str(map, "label", index, bar_index, id_ref)?,
        }),
        "line" => DrawingKind::Line(LineDrawing {
            x1: req_time(map, "x1", index, bar_index, id_ref, type_ref)?,
            y1: req_f64(map, "y1", index, bar_index, id_ref, type_ref)?,
            x2: req_time(map, "x2", index, bar_index, id_ref, type_ref)?,
            y2: req_f64(map, "y2", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            line_style: opt_line_style(map, index, bar_index, id_ref)?,
            width: opt_width(map, index, bar_index, id_ref)?,
        }),
        "rectangle" => DrawingKind::Rectangle(RectangleDrawing {
            time_start: req_time(map, "time_start", index, bar_index, id_ref, type_ref)?,
            time_end: opt_time(map, "time_end", index, bar_index, id_ref)?,
            price_top: req_f64(map, "price_top", index, bar_index, id_ref, type_ref)?,
            price_bot: req_f64(map, "price_bot", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            opacity: opt_opacity(map, index, bar_index, id_ref)?,
            border: opt_color(map, "border", index, bar_index, id_ref)?,
            label: opt_str(map, "label", index, bar_index, id_ref)?,
        }),
        "region" => DrawingKind::Region(RegionDrawing {
            time_start: req_time(map, "time_start", index, bar_index, id_ref, type_ref)?,
            time_end: req_time(map, "time_end", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            opacity: opt_opacity(map, index, bar_index, id_ref)?,
            label: opt_str(map, "label", index, bar_index, id_ref)?,
        }),
        "marker" => DrawingKind::Marker(MarkerDrawing {
            time: req_time(map, "time", index, bar_index, id_ref, type_ref)?,
            position: match map.get("position") {
                None | Some(Value::Null) => MarkerPosition::Below,
                Some(Value::String(s)) => match s.as_str() {
                    "above" => MarkerPosition::Above,
                    "below" => MarkerPosition::Below,
                    other => {
                        return Err(invalid_value(
                            "position",
                            &Value::String(other.to_string()),
                            "must be 'above' or 'below'",
                            index,
                            bar_index,
                            id_ref,
                        ))
                    }
                },
                Some(other) => {
                    return Err(invalid_value(
                        "position",
                        other,
                        "must be a string",
                        index,
                        bar_index,
                        id_ref,
                    ))
                }
            },
            shape: match map.get("shape") {
                None | Some(Value::Null) => MarkerShape::Circle,
                Some(Value::String(s)) => match s.as_str() {
                    "circle" => MarkerShape::Circle,
                    "square" => MarkerShape::Square,
                    "arrow_up" => MarkerShape::ArrowUp,
                    "arrow_down" => MarkerShape::ArrowDown,
                    other => {
                        return Err(invalid_value(
                            "shape",
                            &Value::String(other.to_string()),
                            "must be 'circle', 'square', 'arrow_up' or 'arrow_down'",
                            index,
                            bar_index,
                            id_ref,
                        ))
                    }
                },
                Some(other) => {
                    return Err(invalid_value("shape", other, "must be a string", index, bar_index, id_ref))
                }
            },
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            text: opt_str(map, "text", index, bar_index, id_ref)?,
        }),
        "label" => DrawingKind::Label(LabelDrawing {
            time: req_time(map, "time", index, bar_index, id_ref, type_ref)?,
            price: req_f64(map, "price", index, bar_index, id_ref, type_ref)?,
            text: req_str(map, "text", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
            position: match map.get("position") {
                None | Some(Value::Null) => LabelPosition::Above,
                Some(Value::String(s)) => match s.as_str() {
                    "above" => LabelPosition::Above,
                    "below" => LabelPosition::Below,
                    "left" => LabelPosition::Left,
                    "right" => LabelPosition::Right,
                    other => {
                        return Err(invalid_value(
                            "position",
                            &Value::String(other.to_string()),
                            "must be 'above', 'below', 'left' or 'right'",
                            index,
                            bar_index,
                            id_ref,
                        ))
                    }
                },
                Some(other) => {
                    return Err(invalid_value(
                        "position",
                        other,
                        "must be a string",
                        index,
                        bar_index,
                        id_ref,
                    ))
                }
            },
        }),
        "bar_color" => DrawingKind::BarColor(BarColorDrawing {
            time: req_time(map, "time", index, bar_index, id_ref, type_ref)?,
            color: req_color(map, "color", index, bar_index, id_ref, type_ref)?,
        }),
        other => {
            return Err(DrawingError::new(
                "DRAWING_TYPE_INVALID",
                format!(
                    "drawing '{id}': unknown type '{other}' (expected series, hline, line, rectangle, region, marker or label)"
                ),
                json!({ "index": index, "bar_index": bar_index, "drawing_id": id, "drawing_type": other }),
            ))
        }
    };

    Ok(DrawingInstruction {
        id,
        action,
        kind: Some(kind),
    })
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(values: Vec<Value>) -> Result<Vec<DrawingInstruction>, DrawingError> {
        DrawingRegistry::new().parse_bar(&values, 0)
    }

    fn err(values: Vec<Value>) -> DrawingError {
        parse(values).expect_err("expected a validation error")
    }

    #[test]
    fn accepts_every_public_type() {
        let values = vec![
            json!({"id":"s1","type":"series","value":1.1,"color":"#58a6ff"}),
            json!({"id":"h1","type":"hline","price":1.1,"color":"#d29922","label":"POC"}),
            json!({"id":"l1","type":"line","x1":"2024-01-01T00:00:00Z","y1":1.0,"x2":"2024-01-01T00:15:00Z","y2":1.1,"color":"#8957e5"}),
            json!({"id":"r1","type":"rectangle","time_start":"2024-01-01T00:00:00Z","time_end":null,"price_top":1.1,"price_bot":1.0,"color":"#3fb950","opacity":0.14}),
            json!({"id":"g1","type":"region","time_start":"2024-01-01T00:00:00Z","time_end":"2024-01-01T01:00:00Z","color":"#58a6ff","label":"London"}),
            json!({"id":"m1","type":"marker","time":"2024-01-01T00:00:00Z","position":"above","shape":"arrow_up","color":"#3fb950","text":"long"}),
            json!({"id":"n1","type":"label","time":"2024-01-01T00:00:00Z","price":1.1,"text":"RSI 27","color":"#f85149","position":"left"}),
        ];
        let parsed = parse(values).unwrap();
        assert_eq!(parsed.len(), 7);
        assert_eq!(parsed[0].kind.as_ref().unwrap().tag(), "series");
        assert_eq!(parsed[6].kind.as_ref().unwrap().tag(), "label");
    }

    #[test]
    fn series_none_value_is_a_gap_not_zero() {
        let parsed = parse(vec![json!({"id":"s","type":"series","value":null,"color":"#58a6ff"})]).unwrap();
        match parsed[0].kind.as_ref().unwrap() {
            DrawingKind::Series(s) => assert!(s.value.is_none()),
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn remove_carries_no_kind() {
        let parsed = parse(vec![json!({"id":"s","type":"series","value":1.0,"color":"#58a6ff"})]).unwrap();
        assert!(parsed[0].kind.is_some());
        let mut registry = DrawingRegistry::new();
        let _ = registry
            .parse_bar(&[json!({"id":"s","type":"series","value":1.0,"color":"#58a6ff"})], 0)
            .unwrap();
        let removed = registry
            .parse_bar(&[json!({"id":"s","action":"remove"})], 1)
            .unwrap();
        assert!(removed[0].kind.is_none());
        assert!(registry.live_ids().is_empty());
    }

    #[test]
    fn error_codes_are_stable() {
        assert_eq!(err(vec![json!({"id":"a","type":"nope"})]).code, "DRAWING_TYPE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"hline","color":"#fff"})]).code, "DRAWING_FIELD_MISSING");
        assert_eq!(err(vec![json!({"id":"a","type":"hline","price":"x","color":"#ffffff"})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"bad id","type":"hline","price":1.0,"color":"#ffffff"})]).code, "DRAWING_ID_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"series","value":1.0,"color":"#ffffff","pane":"top"})]).code, "DRAWING_PANE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"label","time":"nope","price":1.0,"text":"t","color":"#ffffff"})]).code, "DRAWING_TIME_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"hline","price":1.0,"color":"#ffffff","action":"frobnicate"})]).code, "DRAWING_ACTION_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"hline","price":1.0,"color":"red"})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"series","value":1.0,"color":"#ffffff","width":9})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"rectangle","time_start":"2024-01-01T00:00:00Z","price_top":1.0,"price_bot":0.9,"color":"#ffffff","opacity":2.0})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"hline","price":1.0,"color":"#ffffff","line_style":"wavy"})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"marker","time":"2024-01-01T00:00:00Z","color":"#ffffff","shape":"star"})]).code, "DRAWING_VALUE_INVALID");
        assert_eq!(err(vec![json!({"id":"a","type":"label","time":"2024-01-01T00:00:00Z","price":1.0,"text":"t","color":"#ffffff","position":"middle"})]).code, "DRAWING_VALUE_INVALID");
    }

    #[test]
    fn lifecycle_rules() {
        let mut registry = DrawingRegistry::new();
        registry
            .parse_bar(&[json!({"id":"z","type":"rectangle","time_start":"2024-01-01T00:00:00Z","price_top":1.1,"price_bot":1.0,"color":"#3fb950"})], 0)
            .unwrap();
        // update with the same type is fine
        registry
            .parse_bar(&[json!({"id":"z","type":"rectangle","action":"update","time_start":"2024-01-01T00:00:00Z","price_top":1.2,"price_bot":1.0,"color":"#3fb950"})], 1)
            .unwrap();
        // update with a different type is invalid
        let e = registry
            .parse_bar(&[json!({"id":"z","type":"hline","action":"update","price":1.0,"color":"#ffffff"})], 2)
            .unwrap_err();
        assert_eq!(e.code, "DRAWING_ACTION_INVALID");
        // add over an existing non-series id is invalid
        let e = registry
            .parse_bar(&[json!({"id":"z","type":"hline","price":1.0,"color":"#ffffff"})], 2)
            .unwrap_err();
        assert_eq!(e.code, "DRAWING_ACTION_INVALID");
        // unknown update / remove are invalid
        assert_eq!(
            registry.parse_bar(&[json!({"id":"nope","type":"hline","action":"update","price":1.0,"color":"#ffffff"})], 2).unwrap_err().code,
            "DRAWING_REFERENCE_INVALID"
        );
        assert_eq!(
            registry.parse_bar(&[json!({"id":"nope","action":"remove"})], 2).unwrap_err().code,
            "DRAWING_REFERENCE_INVALID"
        );
        // remove then re-add the same id is fine
        registry.parse_bar(&[json!({"id":"z","action":"remove"})], 3).unwrap();
        registry
            .parse_bar(&[json!({"id":"z","type":"hline","price":1.0,"color":"#ffffff"})], 4)
            .unwrap();
    }

    #[test]
    fn series_add_appends_and_update_is_invalid() {
        let mut registry = DrawingRegistry::new();
        for i in 0..3 {
            registry
                .parse_bar(&[json!({"id":"ema","type":"series","value":i,"color":"#58a6ff"})], i)
                .unwrap();
        }
        assert_eq!(registry.live_ids(), vec!["ema"]);
        let e = registry
            .parse_bar(&[json!({"id":"ema","type":"series","action":"update","value":3.0,"color":"#58a6ff"})], 3)
            .unwrap_err();
        assert_eq!(e.code, "DRAWING_ACTION_INVALID");
    }

    #[test]
    fn per_bar_limit_is_enforced() {
        let values: Vec<Value> = (0..=MAX_DRAWINGS_PER_BAR)
            .map(|i| json!({"id": format!("h{i}"), "type":"hline","price":1.0,"color":"#ffffff"}))
            .collect();
        let e = err(values);
        assert_eq!(e.code, "DRAWING_LIMIT_EXCEEDED");
        assert_eq!(e.details["limit"], json!(MAX_DRAWINGS_PER_BAR));
    }

    #[test]
    fn deprecated_fields_are_accepted_and_ignored() {
        let parsed = parse(vec![json!({
            "id":"z","type":"rectangle",
            "time_start":"2024-01-01T00:00:00Z","time_end":null,
            "price_top":1.1,"price_bot":1.0,"color":"#3fb950",
            "persist":"until_filled","fill_price":1.0,
            "style":"dashed","extend":true,"bg_color":"#000000"
        })])
        .unwrap();
        assert_eq!(parsed.len(), 1);
    }

    #[test]
    fn instruction_round_trips_through_json() {
        let values = vec![
            json!({"id":"s1","type":"series","value":1.1,"color":"#58a6ff","pane":"separate","series_type":"histogram","line_style":"dashed","width":2,"label":"EMA 20"}),
            json!({"id":"h1","type":"hline","price":1.1,"color":"#d29922"}),
            json!({"id":"m1","type":"marker","time":"2024-01-01T00:00:00Z","shape":"square","color":"#3fb950"}),
        ];
        let parsed = parse(values).unwrap();
        let json = serde_json::to_string(&parsed).unwrap();
        let back: Vec<DrawingInstruction> = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, back, "instructions must survive the canonical JSON round-trip");
        let mut registry = DrawingRegistry::new();
        registry
            .parse_bar(&[json!({"id":"x","type":"hline","price":1.0,"color":"#ffffff"})], 0)
            .unwrap();
        let removed = registry.parse_bar(&[json!({"id":"x","action":"remove"})], 1).unwrap();
        let json = serde_json::to_string(&removed).unwrap();
        assert_eq!(json, r#"[{"id":"x","action":"remove"}]"#);
        let back: Vec<DrawingInstruction> = serde_json::from_str(&json).unwrap();
        assert_eq!(removed, back);
    }
}
