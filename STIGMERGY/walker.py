import time

from src.generate_sparQL import retrieve_blurbs, strongest_communities
from src.helper import _execute_sparQL_command, _generate_sparQL, timed_stage
from src.preprocessing import _ontology_embedding_similarity, _summary_embedding_similarity
from src.walker import walk


if __name__ == "__main__":
    with timed_stage("Total pipeline"):
        # with timed_stage("Ontology preprocessing"):
        #     _ontology_embedding_similarity()

        # with timed_stage("Summary preprocessing"):
        #     _summary_embedding_similarity()

        # with timed_stage("Blackboard walk"):
        #     walk(trial_count=3, steps_per_trial=5) # number of steps do not include the HNSW entry point community

        with timed_stage("SPARQL generation"):
            _generate_sparQL()