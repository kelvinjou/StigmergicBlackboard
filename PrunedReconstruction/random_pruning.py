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
DETACHED_OUTPUT_TTL = REPO_ROOT / "GeneratedTTLs" / "detached.ttl"
MODIFIED_ORIGINAL = REPO_ROOT / "GeneratedTTLs" / "modified_original.ttl"

g = Graph()
g.parse(INPUT_TTL, format="turtle")

EX = Namespace("http://example.org/3dui-ontology#")
root_class = EX.WayfindingTechnique

# step down into descendants transitively
branch_classes = set(g.transitive_subjects(RDFS.subClassOf, root_class))
branch_classes.add(root_class) # include the root itself (?)

detached_g = Graph()
modified_g = g
# preprocess
for prefix, ns in g.namespaces():
    detached_g.bind(prefix, ns)

for cls in branch_classes:
    # only get classes where the specified class is under the target root class 
    # what the class says abt itself (as subject)
    for triple in g.triples((cls, None, None)):
        detached_g.add(triple)
        modified_g.remove(triple)
    
    # everything that references this class
    for triple in g.triples((None, None, cls)):
        detached_g.add(triple)
        modified_g.remove(triple)

DETACHED_OUTPUT_TTL.parent.mkdir(parents=True, exist_ok=True)
detached_g.serialize(destination=DETACHED_OUTPUT_TTL, format="turtle")
print(f"Extracted {len(detached_g)} triples for {len(branch_classes)} classes.")

MODIFIED_ORIGINAL.parent.mkdir(parents=True, exist_ok=True)
modified_g.serialize(destination=MODIFIED_ORIGINAL, format="turtle")
print("Modified Original")

# generate description with LLM before pruning


