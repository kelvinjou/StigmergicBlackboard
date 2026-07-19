STIGMERGY/
├── walker.py
│   └── small compatibility entrypoint that calls src.walker.walk()
├── src/
│   ├── __init__.py
│   ├── walker.py
│   │   ├── _generate_llm_relational_description()
│   │   ├── _compare_similarity_at_walk()
│   │   └── walk()
│   ├── preprocessing.py
│   │   ├── _ontology_embedding_similarity()
│   │   └── _summary_embedding_similarity()
│   ├── walk_strategies.py
│   │   ├── _seed_random_comm()
│   │   ├── _get_communities()
│   │   ├── _starting_community()
│   │   ├── _adjacent_walk()
│   │   ├── _direct_child_walk()
│   │   └── _levy_jump()
└── llm/
    ├── lmstudio_llm.py
    ├── nvidia_nim_llm.py
    └── prompts/
        ├── baseline_sys_prompt.md
        ├── sparQL_generation_sys_prompt.md
        └── system_prompt.md
