import pandas as pd
import numpy as np
import random
from pathlib import Path

# Fixed random seed
SEED = 20261022

random.seed(SEED)
np.random.seed(SEED)

# Project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Output folder
MASTER_DIR = BASE_DIR / "data" / "master"
MASTER_DIR.mkdir(parents=True, exist_ok=True)

# Generate 100 learners (starter dataset)
learners = []

for i in range(1, 101):

    learner_id = f"LRN-{i:06d}"

    learner = {
        "learner_id": learner_id,
        "learner_name": f"Learner {i}",
        "experience_level": random.choice(
            ["Beginner", "Intermediate", "Advanced"]
        ),
        "learner_status": "Active"
    }

    learners.append(learner)

# Convert into DataFrame
df = pd.DataFrame(learners)

# Save CSV
df.to_csv(MASTER_DIR / "learners.csv", index=False)

print("Learner data generated successfully!")
print("Total learners:", len(df))
print(df.head())

# Generate Courses

courses = []

course_names = [
    "Python Programming",
    "Data Analytics",
    "Machine Learning",
    "SQL Database",
    "Statistics",
    "Data Science",
    "Web Development",
    "Artificial Intelligence",
    "Deep Learning",
    "Business Analytics",
    "Python for Data Science",
    "Advanced SQL",
    "Data Visualization",
    "Excel Analytics",
    "Probability",
    "Linear Algebra",
    "Flask Development",
    "Database Management",
    "Data Engineering",
    "Generative AI"
]

for i, name in enumerate(course_names, start=1):

    course = {
        "course_id": f"CRS-{i:06d}",
        "course_name": name,
        "course_status": "Active"
    }

    courses.append(course)

courses_df = pd.DataFrame(courses)

courses_df.to_csv(
    MASTER_DIR / "courses.csv",
    index=False
)

print("Courses generated:", len(courses_df))

#skills generate
# Generate Skills

skills = []

skill_names = [
    "Python Basics",
    "Variables",
    "Data Types",
    "Operators",
    "Conditional Statements",
    "Loops",
    "Functions",
    "Lists",
    "Tuples",
    "Dictionaries",
    "Sets",
    "Strings",
    "File Handling",
    "Exception Handling",
    "OOP",
    "SQL Basics",
    "SQL Joins",
    "SQL Group By",
    "Statistics",
    "Data Visualization"
]

for i, name in enumerate(skill_names, start=1):

    skill = {
        "skill_id": f"SKL-{i:06d}",
        "skill_name": name,
        "difficulty_level": random.choice(
            ["Beginner", "Intermediate", "Advanced"]
        )
    }

    skills.append(skill)

skills_df = pd.DataFrame(skills)

skills_df.to_csv(
    MASTER_DIR / "skills.csv",
    index=False
)

print("Skills generated:", len(skills_df))


#skill generation
# Generate Skill Prerequisites

prerequisites = [
    ("SKL-000002", "SKL-000001"),
    ("SKL-000003", "SKL-000002"),
    ("SKL-000004", "SKL-000003"),
    ("SKL-000005", "SKL-000004"),
    ("SKL-000006", "SKL-000005"),
    ("SKL-000007", "SKL-000001"),
    ("SKL-000008", "SKL-000001"),
    ("SKL-000009", "SKL-000008"),
    ("SKL-000010", "SKL-000008"),
    ("SKL-000013", "SKL-000007"),
    ("SKL-000014", "SKL-000007"),
    ("SKL-000015", "SKL-000007"),
    ("SKL-000017", "SKL-000016"),
    ("SKL-000018", "SKL-000017"),
    ("SKL-000020", "SKL-000019")
]

prerequisite_records = []

for i, (skill, prerequisite) in enumerate(prerequisites, start=1):

    record = {
        "prerequisite_id": f"PRQ-{i:06d}",
        "skill_id": skill,
        "prerequisite_skill_id": prerequisite
    }

    prerequisite_records.append(record)

prerequisite_df = pd.DataFrame(prerequisite_records)

prerequisite_df.to_csv(
    MASTER_DIR / "skill_prerequisites.csv",
    index=False
)

print("Prerequisites generated:", len(prerequisite_df))

#conetent items
# Generate Content Items

content_items = []

content_types = [
    "Video",
    "PDF",
    "Quiz",
    "Exercise",
    "Project"
]

difficulty_levels = [
    "Beginner",
    "Intermediate",
    "Advanced"
]

for i in range(1, 51):

    content = {
        "content_id": f"CNT-{i:06d}",
        "course_id": f"CRS-{((i-1) % 20)+1:06d}",
        "content_title": f"Learning Activity {i}",
        "content_type": random.choice(content_types),
        "difficulty_level": random.choice(difficulty_levels),
        "duration_minutes": random.choice([15, 30, 45, 60]),
        "content_status": "Active"
    }

    content_items.append(content)

content_df = pd.DataFrame(content_items)

content_df.to_csv(
    MASTER_DIR / "content_items.csv",
    index=False
)

print("Content items generated:", len(content_df))


#content skills mapping
# Generate ContentSkill Mapping

content_skills = []

for i in range(1, 51):

    skill_number = ((i - 1) % 20) + 1

    content_skills.append({
        "content_skill_id": f"CSM-{i:06d}",
        "content_id": f"CNT-{i:06d}",
        "skill_id": f"SKL-{skill_number:06d}"
    })

# Add 10 additional mappings
for i in range(1, 11):

    content_skills.append({
        "content_skill_id": f"CSM-{50+i:06d}",
        "content_id": f"CNT-{i:06d}",
        "skill_id": f"SKL-{((i+9) % 20)+1:06d}"
    })

content_skills_df = pd.DataFrame(content_skills)

content_skills_df.to_csv(
    MASTER_DIR / "content_skills.csv",
    index=False
)

print("Content skill mappings:", len(content_skills_df))