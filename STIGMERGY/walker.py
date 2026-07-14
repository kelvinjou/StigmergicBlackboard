from src.generate_sparQL import retrieve_blurbs, strongest_communities
from src.helper import _execute_sparQL_command, _generate_sparQL
from src.preprocessing import _summary_embedding_similarity
from src.walker import walk


if __name__ == "__main__":
    # _summary_embedding_similarity()
    # walk(trial_count=3, steps_per_trial=10)

    _generate_sparQL()