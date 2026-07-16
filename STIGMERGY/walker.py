from src.generate_sparQL import retrieve_blurbs, strongest_communities
from src.helper import _execute_sparQL_command, _generate_sparQL
from src.preprocessing import _summary_embedding_similarity
from src.walker import walk


if __name__ == "__main__":
    # pre-processing
    # _summary_embedding_similarity()

    # creates the blackboard
    # walk(trial_count=3, steps_per_trial=5)

    # uses the blackboard to generate sparQL
    _generate_sparQL()