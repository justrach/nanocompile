//! Workspace root crate: intern + graph.

use nano_graph::Graph;
use nano_intern::Interner;

pub fn shortest_named_path(edges: &[(&str, &str)], start: &str, goal: &str) -> Option<Vec<String>> {
    let mut graph = Graph::new();
    for (from, to) in edges {
        graph.add_edge(from, to);
    }
    graph.bfs(start, goal)
}

pub fn unique_labels(labels: &[&str]) -> usize {
    let mut intern = Interner::new();
    intern.intern_many(labels.iter().copied());
    intern.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_a_path() {
        let path = shortest_named_path(
            &[("a", "b"), ("b", "c"), ("a", "c")],
            "a",
            "c",
        );
        assert!(path.is_some());
        assert_eq!(path.unwrap()[0], "a");
    }

    #[test]
    fn counts_unique_labels() {
        assert_eq!(unique_labels(&["x", "y", "x"]), 2);
    }
}
