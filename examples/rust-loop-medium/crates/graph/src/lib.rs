//! Adjacency graph with interned labels. Downstream of nano-intern.

use nano_intern::{Interner, Symbol};
use std::collections::{HashMap, VecDeque};

#[derive(Default)]
pub struct Graph {
    intern: Interner,
    by_name: HashMap<String, Symbol>,
    edges: HashMap<Symbol, Vec<Symbol>>,
}

impl Graph {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_edge(&mut self, from: &str, to: &str) {
        let src = self.intern_name(from);
        let dst = self.intern_name(to);
        self.edges.entry(src).or_default().push(dst);
        self.edges.entry(dst).or_default();
    }

    fn intern_name(&mut self, name: &str) -> Symbol {
        if let Some(id) = self.by_name.get(name) {
            return *id;
        }
        let id = self.intern.intern(name);
        self.by_name.insert(name.to_string(), id);
        id
    }

    pub fn neighbors(&self, name: &str) -> Vec<String> {
        let Some(id) = self.by_name.get(name) else {
            return Vec::new();
        };
        self.edges
            .get(id)
            .into_iter()
            .flatten()
            .filter_map(|next| self.intern.get(*next).map(str::to_string))
            .collect()
    }

    pub fn bfs(&self, start: &str, goal: &str) -> Option<Vec<String>> {
        let start_id = *self.by_name.get(start)?;
        let goal_id = *self.by_name.get(goal)?;
        let mut prev: HashMap<Symbol, Symbol> = HashMap::new();
        let mut seen = vec![start_id];
        let mut q = VecDeque::from([start_id]);
        while let Some(node) = q.pop_front() {
            if node == goal_id {
                let mut path = vec![node];
                let mut cur = node;
                while let Some(p) = prev.get(&cur) {
                    path.push(*p);
                    cur = *p;
                }
                path.reverse();
                return Some(
                    path.into_iter()
                        .filter_map(|id| self.intern.get(id).map(str::to_string))
                        .collect(),
                );
            }
            for next in self.edges.get(&node).into_iter().flatten() {
                if !seen.contains(next) {
                    seen.push(*next);
                    prev.insert(*next, node);
                    q.push_back(*next);
                }
            }
        }
        None
    }

    pub fn node_count(&self) -> usize {
        self.edges.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn walks_two_hops() {
        let mut graph = Graph::new();
        graph.add_edge("a", "b");
        graph.add_edge("b", "c");
        assert_eq!(graph.bfs("a", "c").unwrap(), ["a", "b", "c"]);
    }
}
