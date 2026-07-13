from src.preprocessing import _summary_embedding_similarity
from src.walker import walk


if __name__ == "__main__":
    _summary_embedding_similarity()
    walk(trial_count=3, steps_per_trial=10)
