use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};

use observa_core::drawings::{
    BarColorDrawing, DrawingAction, DrawingInstruction,
    DrawingKind, HLineDrawing, LabelDrawing, LabelPosition,
    LineDrawing, LineStyle, Persist, RectangleDrawing,
    RegionDrawing,
};

use crate::error::BridgeError;

/// Parses a Python list of drawing dicts into
/// a Vec<DrawingInstruction>.
///
/// Called after on_bar() returns a dict with
/// a 'drawings' key.
pub fn drawings_from_py(
    py: Python,
    obj: &Bound<PyAny>,
) -> Result<Vec<DrawingInstruction>, BridgeError> {
    let list = obj.downcast::<PyList>().map_err(|_| {
        BridgeError::InvalidSignal(
            "'drawings' must be a list".to_string()
        )
    })?;

    list.iter()
        .map(|item| drawing_from_py(py, &item))
        .collect()
}

fn drawing_from_py(
    _py: Python,
    obj: &Bound<PyAny>,
) -> Result<DrawingInstruction, BridgeError> {
    let dict = obj.downcast::<PyDict>().map_err(|_| {
        BridgeError::InvalidSignal(
            "each drawing must be a dict".to_string()
        )
    })?;

    // id — required
    let id: String = dict
        .get_item("id")
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            "'id' is required on every drawing".to_string()
        ))?
        .extract()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?;

    // action — optional, defaults to "add"
    let action = dict
        .get_item("action")
        .ok()
        .flatten()
        .and_then(|v| v.extract::<String>().ok())
        .map(|s| match s.to_lowercase().as_str() {
            "update" => DrawingAction::Update,
            "remove" => DrawingAction::Remove,
            _        => DrawingAction::Add,
        })
        .unwrap_or(DrawingAction::Add);

    // If action is Remove, we don't need the drawing details
    if action == DrawingAction::Remove {
        return Ok(DrawingInstruction {
            id,
            action,
            kind: DrawingKind::Label(LabelDrawing {
                time:     String::new(),
                price:    0.0,
                text:     String::new(),
                color:    String::new(),
                bg_color: None,
                position: LabelPosition::Above,
            }),
        });
    }

    // type — required for add/update
    let drawing_type: String = dict
        .get_item("type")
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            "'type' is required on every drawing".to_string()
        ))?
        .extract()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?;

    let kind = match drawing_type.as_str() {
        "rectangle" => parse_rectangle(dict)?,
        "hline"     => parse_hline(dict)?,
        "line"      => parse_line(dict)?,
        "label"     => parse_label(dict)?,
        "region"    => parse_region(dict)?,
        "bar_color" => parse_bar_color(dict)?,
        other => return Err(BridgeError::InvalidSignal(
            format!("unknown drawing type '{}'", other)
        )),
    };

    Ok(DrawingInstruction { id, action, kind })
}

// ── Parsers for each drawing type ────────────────

fn get_str(dict: &Bound<PyDict>, key: &str) -> Result<String, BridgeError> {
    dict.get_item(key)
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            format!("'{}' is required", key)
        ))?
        .extract::<String>()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))
}

fn get_f64(dict: &Bound<PyDict>, key: &str) -> Result<f64, BridgeError> {
    dict.get_item(key)
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            format!("'{}' is required", key)
        ))?
        .extract::<f64>()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))
}

fn get_optional_str(dict: &Bound<PyDict>, key: &str) -> Option<String> {
    dict.get_item(key).ok().flatten()
        .and_then(|v| if v.is_none() { None } else { v.extract::<String>().ok() })
}

fn get_optional_f64(dict: &Bound<PyDict>, key: &str) -> Option<f64> {
    dict.get_item(key).ok().flatten()
        .and_then(|v| if v.is_none() { None } else { v.extract::<f64>().ok() })
}

fn parse_persist(dict: &Bound<PyDict>) -> Persist {
    match dict.get_item("persist").ok().flatten() {
        None => Persist::Permanent,
        Some(v) => {
            if let Ok(s) = v.extract::<String>() {
                match s.as_str() {
                    "permanent"    => Persist::Permanent,
                    "until_filled" => Persist::UntilFilled,
                    _              => Persist::Permanent,
                }
            } else if let Ok(n) = v.extract::<u32>() {
                Persist::NBars(n)
            } else {
                Persist::Permanent
            }
        }
    }
}

fn parse_line_style(dict: &Bound<PyDict>) -> LineStyle {
    dict.get_item("style").ok().flatten()
        .and_then(|v| v.extract::<String>().ok())
        .map(|s| match s.as_str() {
            "dashed" => LineStyle::Dashed,
            "dotted" => LineStyle::Dotted,
            _        => LineStyle::Solid,
        })
        .unwrap_or(LineStyle::Solid)
}

fn parse_width(dict: &Bound<PyDict>) -> u32 {
    dict.get_item("width").ok().flatten()
        .and_then(|v| v.extract::<u32>().ok())
        .unwrap_or(1)
}

fn parse_rectangle(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    Ok(DrawingKind::Rectangle(RectangleDrawing {
        time_start: get_str(dict, "time_start")?,
        time_end:   get_optional_str(dict, "time_end"),
        price_top:  get_f64(dict, "price_top")?,
        price_bot:  get_f64(dict, "price_bot")?,
        color:      get_str(dict, "color")?,
        border:     get_optional_str(dict, "border"),
        persist:    parse_persist(dict),
        fill_price: get_optional_f64(dict, "fill_price"),
    }))
}

fn parse_hline(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    Ok(DrawingKind::Hline(HLineDrawing {
        time:    get_str(dict, "time")?,
        price:   get_f64(dict, "price")?,
        color:   get_str(dict, "color")?,
        style:   parse_line_style(dict),
        width:   parse_width(dict),
        persist: parse_persist(dict),
    }))
}

fn parse_line(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    Ok(DrawingKind::Line(LineDrawing {
        x1:     get_str(dict, "x1")?,
        y1:     get_f64(dict, "y1")?,
        x2:     get_str(dict, "x2")?,
        y2:     get_f64(dict, "y2")?,
        color:  get_str(dict, "color")?,
        style:  parse_line_style(dict),
        width:  parse_width(dict),
        extend: dict.get_item("extend").ok().flatten()
                    .and_then(|v| v.extract::<bool>().ok())
                    .unwrap_or(false),
    }))
}

fn parse_label(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    let position = dict.get_item("position").ok().flatten()
        .and_then(|v| v.extract::<String>().ok())
        .map(|s| match s.as_str() {
            "below" => LabelPosition::Below,
            "left"  => LabelPosition::Left,
            "right" => LabelPosition::Right,
            _       => LabelPosition::Above,
        })
        .unwrap_or(LabelPosition::Above);

    Ok(DrawingKind::Label(LabelDrawing {
        time:     get_str(dict, "time")?,
        price:    get_f64(dict, "price")?,
        text:     get_str(dict, "text")?,
        color:    get_str(dict, "color")
                    .unwrap_or_else(|_| "#e6edf3".to_string()),
        bg_color: get_optional_str(dict, "bg_color"),
        position,
    }))
}

fn parse_region(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    Ok(DrawingKind::Region(RegionDrawing {
        time_start: get_str(dict, "time_start")?,
        time_end:   get_str(dict, "time_end")?,
        color:      get_str(dict, "color")?,
        label:      get_optional_str(dict, "label"),
    }))
}

fn parse_bar_color(dict: &Bound<PyDict>)
    -> Result<DrawingKind, BridgeError>
{
    Ok(DrawingKind::BarColor(BarColorDrawing {
        time:  get_str(dict, "time")?,
        color: get_str(dict, "color")?,
    }))
}