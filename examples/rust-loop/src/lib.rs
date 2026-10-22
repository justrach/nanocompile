//! Tiny no-dependency crate used by the rust-loop declared-task example.

pub fn add(left: i32, right: i32) -> i32 {
    left + right
}

// nano-loop-body
fn probe_body(x: i32) -> i32 {
    x
}

// nano-loop-sig
fn probe_sig(x: i32) -> i32 {
    let _ = probe_body(x);
    x
}

#[cfg(test)]
mod tests {
    use super::add;

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(21, 21), 42);
    }
}
