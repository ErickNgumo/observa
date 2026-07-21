use serde::{Deserialize, Serialize};

// ────────────────────────────────────────────────
// Drawing action — what to do with this instruction
// ────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum DrawingAction {
    Add,
    Update,
    Remove,
}

impl Default for DrawingAction {
    fn default() -> Self {
        DrawingAction::Add
    }
}

// ────────────────────────────────────────────────
// Persistence — when does the drawing disappear?
// ────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Persist {
    /// Never removed automatically
    Permanent,
    /// Removed when price crosses fill_price
    UntilFilled,
    /// Removed after N bars
    NBars(u32),
}

impl Default for Persist {
    fn default() -> Self {
        Persist::Permanent
    }
}

// ────────────────────────────────────────────────
// Line style
// ────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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

// ────────────────────────────────────────────────
// Label position
// ────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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

/// A rectangle — FVGs, order blocks, value areas
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RectangleDrawing {
    pub time_start: String,
    pub time_end:   Option<String>,
    pub price_top:  f64,
    pub price_bot:  f64,
    pub color:      String,
    pub border:     Option<String>,
    #[serde(default)]
    pub persist:    Persist,
    pub fill_price: Option<f64>,
}

/// A horizontal line — liquidity levels, key prices
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HLineDrawing {
    pub time:  String,
    pub price: f64,
    pub color: String,
    #[serde(default)]
    pub style: LineStyle,
    #[serde(default = "default_width")]
    pub width: u32,
    #[serde(default)]
    pub persist: Persist,
}

/// A line between two points — trend lines, structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LineDrawing {
    pub x1:    String,
    pub y1:    f64,
    pub x2:    String,
    pub y2:    f64,
    pub color: String,
    #[serde(default)]
    pub style: LineStyle,
    #[serde(default = "default_width")]
    pub width: u32,
    #[serde(default)]
    pub extend: bool,
}

/// A text label on the chart
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabelDrawing {
    pub time:     String,
    pub price:    f64,
    pub text:     String,
    pub color:    String,
    pub bg_color: Option<String>,
    #[serde(default)]
    pub position: LabelPosition,
}

/// A shaded time region — sessions, news windows
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegionDrawing {
    pub time_start: String,
    pub time_end:   String,
    pub color:      String,
    pub label:      Option<String>,
}

/// Custom bar color override
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarColorDrawing {
    pub time:  String,
    pub color: String,
}

fn default_width() -> u32 { 1 }

// ────────────────────────────────────────────────
// DrawingInstruction — the unified type
// ────────────────────────────────────────────────

/// A single drawing instruction from a strategy.
/// Contains an ID so it can be updated or removed later,
/// an action (add/update/remove), and the drawing kind.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DrawingInstruction {
    /// Unique ID — strategy-assigned, used for updates/removal
    pub id: String,

    /// What to do with this drawing
    #[serde(default)]
    pub action: DrawingAction,

    /// The drawing itself
    #[serde(flatten)]
    pub kind: DrawingKind,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DrawingKind {
    Rectangle(RectangleDrawing),
    Hline(HLineDrawing),
    Line(LineDrawing),
    Label(LabelDrawing),
    Region(RegionDrawing),
    BarColor(BarColorDrawing),
}