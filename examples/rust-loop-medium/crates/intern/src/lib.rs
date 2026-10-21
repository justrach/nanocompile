//! Tiny string intern table used as a depended-on crate for signature edits.

use std::collections::HashMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Symbol(u32);

impl Symbol {
    pub fn as_u32(self) -> u32 {
        self.0
    }
}

#[derive(Default)]
pub struct Interner {
    to_id: HashMap<String, Symbol>,
    to_str: Vec<String>,
}

impl Interner {
    pub fn new() -> Self {
        Self::default()
    }

    // nano-loop-body
    pub fn intern(&mut self, text: &str) -> Symbol {
        if let Some(id) = self.to_id.get(text) {
            return *id;
        }
        let id = Symbol(self.to_str.len() as u32);
        self.to_str.push(text.to_string());
        self.to_id.insert(text.to_string(), id);
        id
    }

    // nano-loop-sig
    pub fn get(&self, id: Symbol) -> Option<&str> {
        self.to_str.get(id.0 as usize).map(String::as_str)
    }

    pub fn len(&self) -> usize {
        self.to_str.len()
    }

    pub fn is_empty(&self) -> bool {
        self.to_str.is_empty()
    }

    pub fn intern_many<I>(&mut self, items: I) -> Vec<Symbol>
    where
        I: IntoIterator,
        I::Item: AsRef<str>,
    {
        items.into_iter().map(|item| self.intern(item.as_ref())).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn intern_is_stable() {
        let mut intern = Interner::new();
        let a = intern.intern("loop");
        let b = intern.intern("loop");
        assert_eq!(a, b);
        assert_eq!(intern.get(a), Some("loop"));
    }
}
