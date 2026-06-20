from scipy import stats
import pandas as pd

df = pd.read_csv("benchmark_results.csv")
agent_group = df.loc[df["experiment_type"] == "agent", "total_tokens"].dropna().to_numpy()
baseline_group = df.loc[df["experiment_type"] == "baseline", "total_tokens"].dropna().to_numpy()
sparql_group = df.loc[df["experiment_type"] == "sparql", "total_tokens"].dropna().to_numpy()


# if len(agent_group) < 2 or len(baseline_group) < 2:
#     raise ValueError(
#         "Need at least two total_tokens values for both agent and baseline groups."
#     )

# t-tests
t_stat, p_value = stats.ttest_ind(agent_group, baseline_group, equal_var=False)

print(f"T-statistic: {t_stat:.4f}")
print(f"P-value: {p_value:.4e}")

if p_value < 0.05:
    print("Result is statistically significant (Reject H0)")
else:
    print("Result is not statistically significant (Fail to reject H0)")
