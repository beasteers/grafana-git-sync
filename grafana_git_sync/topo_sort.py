
from collections import defaultdict

def dict_dependencies(data, keys, ignore=[]):
    '''Recurse through a dictionary finding all references to values within keys.'''
    if isinstance(data, dict):
        data = [v for k, v in data.items() if k not in ignore]
    if isinstance(data, (list, set, tuple)):
        return [k for v in data for k in dict_dependencies(v, keys)]
    return [data] if data in keys else []

def invert_graph(graph):
    '''Invert a node-edge graph from incoming edges to outgoing edges (or vice versa)'''
    inverted_graph = {}
    for node, neighbors in graph.items():
        if node not in inverted_graph: inverted_graph[node] = set()
        for neighbor in neighbors:
            if neighbor not in inverted_graph: inverted_graph[neighbor] = set()
            inverted_graph[neighbor].add(node)
    return inverted_graph

def clean_graph(graph):
    '''Remove self references and ensure the graph keys are fully defined.'''
    for node, neighbors in list(graph.items()):
        for neighbor in list(neighbors):
            if neighbor not in graph:
                graph[neighbor] = set()
            if neighbor == node:
                graph[node].remove(neighbor)
    return graph


def min_topological_sort(graph, flat=True):
    '''Topologically sort a graph. 
    Has the option of returning groups of keys with no inter-dependencies, otherwise it flattens.
    '''
    # graph before inversion can be read as: B depends on {"A"}, C depends on {"B"}, D depends on {"B"}
    graph = invert_graph(graph)
    # graph after inversion can be read as: A is required for {"B"}, B is required for {"C", "D"}
    graph = clean_graph(graph)
    # after cleaning, graph has all nodes at the top level and contains no direct self-references
    indegree = defaultdict(int)
    for node, neighbors in graph.items():
        for neighbor in neighbors:
            indegree[neighbor] += 1

    sets = []
    current_set = set(node for node in graph if indegree[node] == 0)
    while current_set:
        sets.append(current_set.copy())
        next_set = set()
        for node in current_set:
            for neighbor in graph.get(node, []):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    next_set.add(neighbor)

        current_set = next_set
    
    missing = set(x for xs in sets for x in xs) - set(graph)
    assert not missing, missing
    if flat:
        sets = [x for xs in sets for x in xs]
    return sets

def create_graph_from_items(items, id_key='id'):
    '''Create a graph dictionary from a dict of items.'''
    if not isinstance(items, dict):
        assert id_key
        items = {d[id_key]: d for d in items}
    keys = set(items)
    return clean_graph({
        i: set(dict_dependencies(v, keys, ignore=[id_key]) )
        for i, v in items.items()
    })


if __name__ == '__main__':
    
    def test():
        # Example usage:
        items = [
            {"id": "A", "similar": None},
            {"id": "B", "similar": "A"},
            {"id": "C", "similar": "B", "also_similar": "C"},
            {"id": "D", "similar": "B", "also_similar": None},
        ]
        graph = create_graph_from_items(items, "id")
        print('graph', graph)  # {'A': [], 'B': ['A'], 'C': ['B'], 'D': ['B']}
        sorted_nodes = min_topological_sort(graph, flat=False)
        print("Topological Sort:", sorted_nodes)

    import fire
    fire.Fire(test)