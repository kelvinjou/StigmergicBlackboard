from rdflib import Graph, RDFS, Literal

g = Graph()
g.parse("enhanced_xr.ttl", format="ttl")


# root_nodes = list(g.subjects(RDFS.label, Literal(root_node_label)))
label = Literal("Domain Concept", lang="en")

# there should only be 1 root node with subject Concept, but anyways...
for root_node in g.subjects(RDFS.label, label):
    for s, p, o in g.triples((root_node, None, None)):
        print(s, p, o)

