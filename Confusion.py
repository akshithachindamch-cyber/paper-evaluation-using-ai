import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Class labels
labels = ["Poor", "Average", "Good", "Excellent"]

# Example confusion matrix values
# Rows = Actual (Faculty)
# Columns = Predicted (AI)
confusion_matrix = np.array([
    [8, 1, 0, 0],
    [1, 12, 2, 0],
    [0, 2, 15, 1],
    [0, 0, 1, 10]
])

plt.figure(figsize=(8, 6))
sns.heatmap(
    confusion_matrix,
    annot=True,
    fmt="d",
    cmap="Blues",
    xticklabels=labels,
    yticklabels=labels
)

plt.xlabel("Predicted Class (AI Evaluation)")
plt.ylabel("Actual Class (Faculty Evaluation)")
plt.title("Confusion Matrix for AI Paper Evaluation System")

plt.tight_layout()
plt.show()
