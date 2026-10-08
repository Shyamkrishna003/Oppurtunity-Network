from django.db import migrations

from taxonomy.models import skill_slug

# A starting vocabulary so the skill picker is useful from day one. Users add more.
SKILLS = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "C",
    "C++",
    "C#",
    "Go",
    "Rust",
    "Kotlin",
    "Swift",
    "PHP",
    "Ruby",
    "Dart",
    "SQL",
    "HTML",
    "CSS",
    "React",
    "Next.js",
    "Vue.js",
    "Angular",
    "Svelte",
    "Node.js",
    "Express",
    "Django",
    "Flask",
    "FastAPI",
    "Spring Boot",
    ".NET",
    "Laravel",
    "Ruby on Rails",
    "Flutter",
    "React Native",
    "Android",
    "iOS",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Elasticsearch",
    "Kafka",
    "RabbitMQ",
    "GraphQL",
    "REST APIs",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "Google Cloud",
    "Terraform",
    "Linux",
    "Git",
    "CI/CD",
    "Nginx",
    "Machine Learning",
    "Data Analysis",
    "Data Engineering",
    "Pandas",
    "NumPy",
    "TensorFlow",
    "PyTorch",
    "UI Design",
    "UX Design",
    "Figma",
    "Product Management",
    "Project Management",
    "Agile",
    "Scrum",
    "Technical Writing",
    "Content Writing",
    "Digital Marketing",
    "SEO",
    "Sales",
    "Customer Support",
    "Public Speaking",
    "Community Management",
    "Event Management",
    "Recruiting",
    "Mentoring",
    "Leadership",
    "Cybersecurity",
    "Testing",
    "Test Automation",
    "DevOps",
    "Embedded Systems",
    "Blockchain",
    "Game Development",
]


def seed(apps, schema_editor):
    Skill = apps.get_model("taxonomy", "Skill")
    existing = set(Skill.objects.values_list("slug", flat=True))
    Skill.objects.bulk_create(
        Skill(name=name, slug=slug)
        for name in SKILLS
        if (slug := skill_slug(name)) not in existing
    )


class Migration(migrations.Migration):
    dependencies = [
        ("taxonomy", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
