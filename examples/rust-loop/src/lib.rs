//! Tiny no-dependency crate used by the rust-loop declared-task example.

pub fn add(left: i32, right: i32) -> i32 {
    left + right
}

#[cfg(test)]
mod tests {
    use super::add;

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(21, 21), 42);
    }
}
