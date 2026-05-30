# take out a portion of the graph using prune() function
# generate a summary based on the pruned component (into a human like report).
    # Have it describe what the component is about, but has no context about relative placement
# have llm insert it back in (using the three rows to determine placement)


"""
complete this prune(level, n)  (n times so that the ontology gets smaller and smaller each time. 
Maybe ask it to create a general summary of the ontology. See how it loses details?

choose one node nth level down, detach

find a community n levels down
    - create a temp ttl file that has any references from that spec. community
"""

from pathlib import Path

from rdflib import RDFS, Graph, Namespace

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_TTL = REPO_ROOT / "enhanced_xr.ttl"
OUTPUT_TTL = REPO_ROOT / "GeneratedTTLs" / "detached.ttl"

g = Graph()
g.parse(INPUT_TTL, format="turtle")

EX = Namespace("http://example.org/3dui-ontology#")
root_class = EX.WayfindingTechnique

# step down into descendants transitively
branch_classes = set(g.transitive_subjects(RDFS.subClassOf, root_class))
branch_classes.add(root_class) # include the root itself (?)

new_g = Graph()
# preprocess
for prefix, ns in g.namespaces():
    new_g.bind(prefix, ns)

for cls in branch_classes:
    # only get classes where the specified class is under the target root class 
    # what the class says abt itself (as subject)
    for triple in g.triples((cls, None, None)):
        new_g.add(triple)
    
    # everything that references this class
    for triple in g.triples((None, None, cls)):
        new_g.add(triple)

OUTPUT_TTL.parent.mkdir(parents=True, exist_ok=True)
new_g.serialize(destination=OUTPUT_TTL, format="turtle")
print(f"Extracted {len(new_g)} triples for {len(branch_classes)} classes.")

# for stmt in g:
#     pprint.pprint(stmt)


# for saving a new copy of the graph: 
# g.serialize(destination="tbl.ttl")
# get all subsequent child references using transitive_subjects (top-down)
