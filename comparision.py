import matplotlib.pyplot as plt

# Sample marks (replace with real values if available)
question_numbers = [1, 2, 3, 4, 5]

faculty_marks = [4.5, 8, 7.5, 9, 6]
ai_marks = [4.0, 8.2, 7.0, 8.8, 6.2]

plt.figure(figsize=(9, 5))

plt.plot(
    question_numbers,
    faculty_marks,
    marker="o",
    linewidth=2,
    label="Faculty Evaluation"
)

plt.plot(
    question_numbers,
    ai_marks,
    marker="s",
    linestyle="--",
    linewidth=2,
    label="AI Evaluation"
)

plt.xlabel("Question Number")
plt.ylabel("Marks")
plt.title("Comparison of AI Evaluation vs Faculty Evaluation")
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()
