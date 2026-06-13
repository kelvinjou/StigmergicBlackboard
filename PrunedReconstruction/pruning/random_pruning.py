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

import sys
from pathlib import Path

from rdflib import RDFS, Graph, Namespace
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.pruning.baseline_summarization import BaselineSummarization
from agent import agent_query


df = pd.read_csv('/Users/kelvinjou/Documents/GitHub/OntologyAgent/Ontology_IN.csv')
COMMUNITIES = df['communities'].loc[df["status"] != "done"]

for COMMUNITY in COMMUNITIES:

    EXPERIMENT_TYPES = ("baseline", "sparql", "agent")

    INPUT_TTL = PROJECT_ROOT / "enhanced_xr.ttl"

    EX = Namespace("http://example.org/3dui-ontology#")

    g = Graph()
    g.parse(INPUT_TTL, format="turtle")

    root_class = EX[COMMUNITY]

    # In-context TTL (baseline) generate description without agent drilling through the layers. 
    # just give it the entire TTL in the context window
    summary = BaselineSummarization()
    baseline_summarization_response = summary.send_messages(f"Generate a thorough description about {COMMUNITY}, and its relations with other communities in the ontology especially communities that are a subclass of it.")
    print(baseline_summarization_response)


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

    for EXPERIMENT_TYPE in EXPERIMENT_TYPES:
        DETACHED_OUTPUT_TTL = PROJECT_ROOT / "dataset" / EXPERIMENT_TYPE / COMMUNITY / "detached.ttl"
        MODIFIED_ORIGINAL = PROJECT_ROOT / "dataset" / EXPERIMENT_TYPE / COMMUNITY / "modified_original.ttl"
        COMMUNITY_SUMMARY = PROJECT_ROOT / "dataset" / EXPERIMENT_TYPE / COMMUNITY / "summary.txt"

        DETACHED_OUTPUT_TTL.parent.mkdir(parents=True, exist_ok=True)
        detached_g.serialize(destination=DETACHED_OUTPUT_TTL, format="turtle")
        print(f"Extracted {len(detached_g)} triples for {len(branch_classes)} classes.")


        MODIFIED_ORIGINAL.parent.mkdir(parents=True, exist_ok=True)
        modified_g.serialize(destination=MODIFIED_ORIGINAL, format="turtle")
        print("Modified Original")

        with open(COMMUNITY_SUMMARY, "w") as f:
            f.write(str(baseline_summarization_response))
