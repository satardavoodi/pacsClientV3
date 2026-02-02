"""
Seed sample courses for Educational Module Library.
Run this once to populate the database with sample courses.
"""

from PacsClient.pacs.education.course_database import insert_course, get_all_courses

# Sample courses covering various modalities and topics
SAMPLE_COURSES = [
    {
        "name": "Advanced MRI Shoulder Pathology",
        "description": "Comprehensive review of rotator cuff tears, labral injuries, and impingement syndromes using MRI. Includes systematic approach to shoulder MR interpretation.",
        "author": "Dr. Sarah Chen, MD",
        "modality": "MRI",
        "level": "Advanced",
        "tags": ["MSK", "Anatomy", "Pathology"],
        "body_regions": ["MSK", "Shoulder"],
    },
    {
        "name": "CT Trauma: Chest and Abdomen",
        "description": "Emergency CT imaging of thoracoabdominal trauma. Focus on rapid identification of life-threatening injuries and systematic trauma CT review.",
        "author": "Dr. Michael Rodriguez, MD",
        "modality": "CT",
        "level": "Intermediate",
        "tags": ["Trauma", "Emergency", "Protocol"],
        "body_regions": ["Chest", "Abdomen"],
    },
    {
        "name": "Neuro MRI: Stroke Imaging",
        "description": "Acute stroke imaging with MRI including DWI, PWI, and MRA. Covers stroke mimics and treatment triage protocols.",
        "author": "Dr. Jennifer Kim, MD, PhD",
        "modality": "MRI",
        "level": "Advanced",
        "tags": ["Emergency", "Protocol", "Pathology"],
        "body_regions": ["Head/Neck"],
    },
    {
        "name": "Basic Chest X-Ray Interpretation",
        "description": "Fundamentals of chest radiography including systematic approach, normal anatomy, and common pathology identification.",
        "author": "Dr. Robert Thompson, MD",
        "modality": "X-Ray",
        "level": "Basic",
        "tags": ["Anatomy", "Pathology"],
        "body_regions": ["Chest"],
    },
    {
        "name": "Pediatric Abdominal Ultrasound",
        "description": "Comprehensive ultrasound techniques for pediatric abdominal imaging including appendicitis, intussusception, and pyloric stenosis.",
        "author": "Dr. Emily Watson, MD",
        "modality": "US",
        "level": "Intermediate",
        "tags": ["Pediatric", "Protocol", "Pathology"],
        "body_regions": ["Abdomen"],
    },
    {
        "name": "Cardiac CT Angiography",
        "description": "CCTA protocol optimization, systematic interpretation, and coronary artery disease assessment. Includes calcium scoring and plaque characterization.",
        "author": "Dr. David Lee, MD",
        "modality": "CT",
        "level": "Advanced",
        "tags": ["Cardiac", "Vascular", "Protocol"],
        "body_regions": ["Cardiac", "Chest"],
    },
    {
        "name": "Spine MRI: Degenerative Disease",
        "description": "Comprehensive review of degenerative spine pathology including disc herniation, stenosis, and spondylolisthesis.",
        "author": "Dr. Lisa Martinez, MD",
        "modality": "MRI",
        "level": "Intermediate",
        "tags": ["MSK", "Pathology", "Anatomy"],
        "body_regions": ["Spine"],
    },
    {
        "name": "Mammography: BI-RADS Essentials",
        "description": "Systematic approach to mammography interpretation using BI-RADS classification. Includes calcification patterns and mass characterization.",
        "author": "Dr. Rachel Green, MD",
        "modality": "Mammography",
        "level": "Intermediate",
        "tags": ["Oncology", "Protocol"],
        "body_regions": ["Chest"],
    },
    {
        "name": "Interventional Radiology: Vascular Access",
        "description": "Fundamentals of ultrasound-guided vascular access including central lines, PICC placement, and troubleshooting.",
        "author": "Dr. James Anderson, MD",
        "modality": "US",
        "level": "Basic",
        "tags": ["Intervention", "Protocol", "Vascular"],
        "body_regions": ["Vascular"],
    },
    {
        "name": "Head CT in Trauma",
        "description": "Rapid interpretation of head CT in trauma patients. Focus on intracranial hemorrhage, skull fractures, and herniation syndromes.",
        "author": "Dr. Amanda Brooks, MD",
        "modality": "CT",
        "level": "Basic",
        "tags": ["Trauma", "Emergency", "Pathology"],
        "body_regions": ["Head/Neck"],
    },
    {
        "name": "MRI Physics and Artifacts",
        "description": "Essential MRI physics concepts and artifact recognition for radiologists. Covers sequence optimization and quality control.",
        "author": "Dr. Kevin Park, PhD",
        "modality": "MRI",
        "level": "Intermediate",
        "tags": ["Physics", "Artifacts", "Protocol"],
        "body_regions": [],
    },
    {
        "name": "Pelvic MRI: Gynecologic Imaging",
        "description": "Comprehensive pelvic MRI techniques and interpretation for gynecologic pathology including fibroids, adenomyosis, and malignancy.",
        "author": "Dr. Maria Santos, MD",
        "modality": "MRI",
        "level": "Advanced",
        "tags": ["Pathology", "Oncology", "Protocol"],
        "body_regions": ["Pelvis"],
    },
]


def seed_courses():
    """Insert sample courses into database."""
    print("Seeding sample courses...")
    
    # Check if courses already exist
    existing = get_all_courses()
    if existing:
        print(f"Found {len(existing)} existing courses.")
        response = input("Do you want to add sample courses anyway? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
    
    # Insert each course
    for i, course in enumerate(SAMPLE_COURSES, 1):
        try:
            course_pk = insert_course(
                name=course["name"],
                description=course["description"],
                author=course["author"],
                modality=course["modality"],
                level=course["level"],
                tags=course["tags"],
                body_regions=course["body_regions"],
                is_my_course=False,  # These are library courses
                is_downloaded=False
            )
            print(f"[{i}/{len(SAMPLE_COURSES)}] Created: {course['name']} (ID: {course_pk})")
        except Exception as e:
            print(f"[{i}/{len(SAMPLE_COURSES)}] ERROR creating {course['name']}: {e}")
    
    print(f"\n✅ Seeding complete! Added {len(SAMPLE_COURSES)} sample courses.")
    print("These courses will appear in the Library tab of the Educational Module.")


if __name__ == "__main__":
    seed_courses()
