"""
Comprehensive Sample Data for Educational Module UI/UX Evaluation
Run this script to populate the database with realistic, detailed example courses.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from modules.education.course_database import (
    insert_course, 
    get_all_courses, 
    delete_course
)

# Comprehensive sample courses with full details for UI/UX evaluation
COMPREHENSIVE_COURSES = [
    {
        "name": "Advanced Brain MRI: Acute Stroke Protocols",
        "description": "Comprehensive guide to acute stroke imaging protocols. This course covers the complete workflow for evaluating acute stroke patients, including diffusion-weighted imaging (DWI), apparent diffusion coefficient (ADC) maps, FLAIR sequences, and perfusion imaging. Learn to identify early ischemic changes, differentiate acute from chronic infarcts, and understand penumbra assessment. Includes 15+ real patient cases with multiparametric sequences and clinical correlations.",
        "author": "Dr. Sarah Mitchell, MD - Neuroradiologist, Stanford Medical Center",
        "outline": "Module 1: Stroke Imaging Fundamentals\n  - Pathophysiology of acute ischemic stroke\n  - Imaging protocol optimization\n  - Time windows and treatment implications\n\nModule 2: DWI and ADC Interpretation\n  - Physics of diffusion imaging\n  - Recognizing restricted diffusion\n  - Pitfalls and mimics\n\nModule 3: Perfusion Imaging\n  - DSC and ASL techniques\n  - Mismatch analysis\n  - Predicting tissue viability\n\nModule 4: Clinical Cases\n  - 15 real stroke cases\n  - Multi-sequence correlation\n  - Treatment decision-making",
        "tags": ["Stroke", "Emergency", "DWI", "Perfusion", "Critical"],
        "modality": "MRI",
        "body_regions": ["Neuro"],
        "level": "Advanced",
        "is_my_course": False,
        "is_downloaded": False
    },
    {
        "name": "Chest CT: COVID-19 Imaging Patterns",
        "description": "Comprehensive course on recognizing and classifying COVID-19 pneumonia patterns on chest CT. Master the imaging findings of COVID-19 at different stages, from early ground-glass opacities to organizing pneumonia. Learn differential diagnosis from other viral and atypical pneumonias. Understand the prognostic implications of various imaging patterns and how they correlate with clinical severity scores. Includes 25+ confirmed COVID cases with clinical outcomes.",
        "author": "Dr. James Chen, MD, FACR - Thoracic Imaging Specialist",
        "outline": "1. COVID-19 Overview and Imaging Role\n  - Pathophysiology of viral pneumonia\n  - When to image and when not to\n  - CT protocols and radiation dose\n\n2. Ground-Glass Opacity (GGO) Patterns\n  - Bilateral, peripheral distribution\n  - Multifocal vs diffuse\n  - Subpleural sparing\n\n3. Crazy Paving and Reticulation\n  - Interlobular septal thickening\n  - Mixed patterns\n  - Time course evolution\n\n4. Consolidation and Organizing Pneumonia\n  - Dense consolidation patterns\n  - Reverse halo sign\n  - Fibrotic changes\n\n5. Differential Diagnosis\n  - Other viral pneumonias\n  - Drug toxicity\n  - Pulmonary edema\n\n6. Clinical Cases\n  - 25 confirmed COVID cases\n  - Severity scoring (CO-RADS)\n  - Clinical correlation",
        "tags": ["COVID-19", "Pneumonia", "Infectious", "Emergency"],
        "modality": "CT",
        "body_regions": ["Chest"],
        "level": "Intermediate",
        "is_my_course": False,
        "is_downloaded": True
    },
    {
        "name": "Musculoskeletal X-Ray: Fracture Recognition Essentials",
        "description": "Essential course for recognizing fracture patterns, understanding fracture classifications, and writing clear radiology reports for emergency and orthopedic imaging. Perfect for residents, emergency physicians, and radiologists developing MSK skills. Learn systematic approach to bone trauma imaging, common pitfalls, normal variants that mimic fractures, and pediatric fracture patterns including Salter-Harris classification. 40+ teaching cases with clinical follow-up.",
        "author": "Dr. Maria Rodriguez, MD - Musculoskeletal Radiologist",
        "outline": "Part 1: Systematic Approach to Bone Trauma\n  - ABCS system for fracture detection\n  - Multiple views and oblique angles\n  - Soft tissue signs of fracture\n  - When to use CT vs MRI\n\nPart 2: Fracture Classification Systems\n  - Descriptive terminology\n  - AO/OTA classification basics\n  - Anatomic vs functional terminology\n\nPart 3: Upper Extremity Fractures\n  - Shoulder girdle injuries\n  - Elbow trauma (terrible triad)\n  - Wrist and hand fractures\n  - Scaphoid fractures and complications\n\nPart 4: Lower Extremity Fractures\n  - Hip fractures (Garden, Pauwels)\n  - Knee trauma\n  - Ankle fractures (Weber, Lauge-Hansen)\n  - Foot injuries\n\nPart 5: Spine Trauma\n  - Cervical spine clearance\n  - Thoracolumbar injury classification\n  - Compression vs burst fractures\n\nPart 6: Pediatric Fractures\n  - Salter-Harris classification\n  - Greenstick, torus fractures\n  - Non-accidental injury patterns\n  - Growth plate injuries\n\nPart 7: Case Studies\n  - 40+ teaching cases\n  - Occult fractures\n  - Common pitfalls",
        "tags": ["Fractures", "Trauma", "Emergency", "Basics"],
        "modality": "X-Ray",
        "body_regions": ["MSK"],
        "level": "Basic",
        "is_my_course": True,
        "is_downloaded": False
    },
    {
        "name": "Abdominal CT: Appendicitis and Mimics",
        "description": "Master the CT diagnosis of acute appendicitis and learn to distinguish it from common mimics in emergency abdominal imaging. This comprehensive course covers normal appendix anatomy and variants, primary and secondary signs of appendicitis, staging of complicated appendicitis, and systematic approach to acute right lower quadrant pain. Special emphasis on differentiating appendicitis from gynecologic pathology, inflammatory bowel disease, and other mimics. 30+ cases with surgical correlation.",
        "author": "Dr. Robert Kim, MD - Emergency & Abdominal Imaging",
        "outline": "1. Appendix Anatomy and Imaging Technique\n  - Normal appendix appearance\n  - Anatomic variants and positions\n  - CT protocol optimization\n  - Oral contrast: yes or no?\n\n2. Primary Signs of Appendicitis\n  - Appendiceal diameter > 6-7mm\n  - Wall thickening and enhancement\n  - Periappendiceal fat stranding\n  - Appendicolith and obstruction\n\n3. Secondary Signs\n  - Cecal apical thickening\n  - Arrow sign\n  - Terminal ileum inflammation\n  - Free fluid\n\n4. Complicated Appendicitis\n  - Perforation signs\n  - Abscess formation\n  - Phlegmon vs abscess\n  - Treatment implications\n\n5. Appendicitis Mimics - GI\n  - Inflammatory bowel disease\n  - Cecal diverticulitis\n  - Epiploic appendagitis\n  - Infectious colitis\n\n6. Appendicitis Mimics - GYN\n  - Ovarian torsion\n  - Ruptured ovarian cyst\n  - Tubo-ovarian abscess\n  - Ectopic pregnancy\n\n7. Other Right Lower Quadrant Pathology\n  - Mesenteric adenitis\n  - Omental infarction\n  - Meckel diverticulitis\n  - Ureteral calculus\n\n8. Case-Based Learning\n  - 30+ surgical correlation cases\n  - Atypical presentations\n  - Negative appendectomy cases",
        "tags": ["Appendicitis", "Acute Abdomen", "Emergency", "GI"],
        "modality": "CT",
        "body_regions": ["Abdomen"],
        "level": "Intermediate",
        "is_my_course": True,
        "is_downloaded": True
    },
    {
        "name": "Ultrasound Physics and Artifacts",
        "description": "Deep dive into ultrasound physics principles and artifact recognition. Essential for all sonographers and radiologists. Understand transducer technology, beam formation, tissue interaction, and Doppler principles. Learn to recognize and troubleshoot common artifacts including shadowing, enhancement, mirror images, reverberation, and side lobes. Optimize your imaging technique and avoid diagnostic pitfalls.",
        "author": "Dr. Lisa Wang, MD - Ultrasound Section Chief",
        "outline": "Section 1: Ultrasound Physics Fundamentals\n  - Sound wave properties\n  - Frequency and wavelength\n  - Acoustic impedance\n  - Attenuation and absorption\n\nSection 2: Transducer Technology\n  - Piezoelectric crystals\n  - Linear vs curvilinear vs phased array\n  - Frequency selection\n  - Focusing and resolution\n\nSection 3: Image Formation\n  - Pulse-echo principle\n  - Time-gain compensation\n  - Dynamic range\n  - Frame rate and temporal resolution\n\nSection 4: Doppler Principles\n  - Color Doppler physics\n  - Spectral Doppler\n  - Aliasing and Nyquist limit\n  - Angle correction\n\nSection 5: Artifacts - Recognition\n  - Acoustic shadowing\n  - Posterior enhancement\n  - Mirror image artifact\n  - Reverberation\n  - Side lobe artifacts\n  - Refraction artifacts\n\nSection 6: Optimization Techniques\n  - Gain adjustment\n  - Focal zone positioning\n  - Frequency optimization\n  - Compound imaging\n  - Harmonic imaging",
        "tags": ["Physics", "Artifacts", "Technical", "Fundamentals"],
        "modality": "Ultrasound",
        "body_regions": ["Technical"],
        "level": "Intermediate",
        "is_my_course": False,
        "is_downloaded": False
    },
    {
        "name": "Cardiac CT: Coronary Artery Disease Assessment",
        "description": "Complete guide to cardiac CT angiography for coronary artery disease evaluation. Learn acquisition protocols, post-processing techniques, and systematic interpretation of coronary CTA. Master the assessment of coronary stenosis, plaque characterization, calcium scoring, and reporting standards (CAD-RADS). Understand indications, contraindications, and clinical decision-making. 50+ cases covering normal anatomy, variants, and full spectrum of CAD.",
        "author": "Dr. Michael Torres, MD - Cardiac Imaging Specialist",
        "outline": "Chapter 1: CCTA Fundamentals\n  - Patient selection and prep\n  - Beta-blocker protocols\n  - Contrast timing and injection\n  - ECG gating strategies\n\nChapter 2: Normal Coronary Anatomy\n  - RCA, LAD, LCx territories\n  - Dominance patterns\n  - Coronary variants\n  - Myocardial bridges\n\nChapter 3: Post-Processing\n  - MPR, CPR, MIP techniques\n  - 3D volume rendering\n  - Centerline analysis\n  - Automated software tools\n\nChapter 4: Stenosis Assessment\n  - Diameter vs area reduction\n  - Hemodynamically significant stenosis\n  - Tandem lesions\n  - Calcification challenges\n\nChapter 5: Plaque Characterization\n  - Non-calcified plaque\n  - Mixed plaque\n  - High-risk features\n  - Napkin-ring sign\n\nChapter 6: CAD-RADS Reporting\n  - 0 to 5 classification\n  - Modifiers (N, S, V)\n  - Management recommendations\n\nChapter 7: Beyond Coronaries\n  - LV function assessment\n  - Valvular evaluation\n  - Myocardial perfusion\n  - Incidental findings\n\nChapter 8: Case Library\n  - 50+ teaching cases\n  - Normal variants\n  - All stenosis grades\n  - Complex anatomy",
        "tags": ["Cardiac", "CAD", "Angiography", "Advanced"],
        "modality": "CT",
        "body_regions": ["Chest"],
        "level": "Advanced",
        "is_my_course": False,
        "is_downloaded": False
    },
    {
        "name": "Pediatric Abdominal Ultrasound: Common Conditions",
        "description": "Comprehensive guide to pediatric abdominal ultrasound for common emergency and outpatient presentations. Covers hypertrophic pyloric stenosis, intussusception, appendicitis in children, ovarian torsion, and renal abnormalities. Special techniques for imaging uncooperative children, normal measurements by age, and pitfalls specific to pediatric imaging. Radiation-free imaging strategies and when to escalate to CT or MRI. 35+ pediatric cases.",
        "author": "Dr. Emily Foster, MD - Pediatric Radiologist",
        "outline": "Module 1: Pediatric US Techniques\n  - Age-appropriate preparation\n  - Transducer selection\n  - Minimizing distress\n  - Parent involvement\n\nModule 2: Hypertrophic Pyloric Stenosis\n  - Target sign appearance\n  - Wall thickness measurements\n  - Length measurements\n  - Gastric outlet visualization\n  - False positives\n\nModule 3: Intussusception\n  - Target/donut sign\n  - Sandwich sign\n  - Trapped fluid\n  - Lead points\n  - Reduction guidance\n\nModule 4: Pediatric Appendicitis\n  - Graded compression technique\n  - Size thresholds in children\n  - Mesenteric adenitis\n  - Avoiding CT in kids\n\nModule 5: Ovarian Pathology\n  - Ovarian torsion signs\n  - Normal ovarian volume by age\n  - Simple vs complex cysts\n  - Teratomas\n\nModule 6: Renal and GU\n  - Hydronephrosis grading\n  - Duplicated collecting systems\n  - Renal stones in children\n  - Bladder evaluation\n\nModule 7: Other Conditions\n  - Hepatosplenomegaly\n  - Biliary atresia screening\n  - Abdominal masses\n\nModule 8: Case Studies\n  - 35+ pediatric cases\n  - Normal variants\n  - Challenging diagnoses",
        "tags": ["Pediatrics", "Ultrasound", "Emergency", "GI"],
        "modality": "Ultrasound",
        "body_regions": ["Abdomen", "Pediatric"],
        "level": "Intermediate",
        "is_my_course": True,
        "is_downloaded": False
    },
    {
        "name": "Knee MRI: Meniscal and Ligament Injuries",
        "description": "Essential MSK course focusing on knee MRI interpretation for sports medicine and orthopedic applications. Systematic approach to evaluating meniscal tears, ACL/PCL injuries, collateral ligaments, and cartilage pathology. Learn grading systems, surgical planning implications, and post-operative appearance. Covers normal anatomy, variants, and complete spectrum of internal derangements. Perfect for radiologists, orthopedic surgeons, and sports medicine physicians. 45+ arthroscopy-correlated cases.",
        "author": "Dr. Thomas Anderson, MD - MSK Imaging Fellowship Director",
        "outline": "Unit 1: Knee MRI Protocols\n  - Standard sequences\n  - High-resolution imaging\n  - 3T vs 1.5T considerations\n  - Fat suppression techniques\n\nUnit 2: Normal Knee Anatomy\n  - Meniscal anatomy\n  - Cruciate ligaments\n  - Collateral ligaments\n  - Cartilage surfaces\n  - Tendons and bursae\n\nUnit 3: Meniscal Tears\n  - Grading system (0-3)\n  - Tear patterns (horizontal, vertical, radial, root)\n  - Bucket-handle tears\n  - Parrot-beak tears\n  - Meniscal cysts\n  - Post-operative changes\n\nUnit 4: Anterior Cruciate Ligament\n  - Primary signs of tear\n  - Secondary signs\n  - Partial vs complete tears\n  - Chronic ACL insufficiency\n  - ACL reconstruction evaluation\n\nUnit 5: Posterior Cruciate Ligament\n  - PCL injury patterns\n  - Associated injuries\n  - Grading system\n\nUnit 6: Collateral Ligaments\n  - MCL injury grading\n  - LCL and posterolateral corner\n  - Pellegrini-Stieda disease\n\nUnit 7: Cartilage Assessment\n  - Outerbridge classification\n  - ICRS grading\n  - Osteochondral lesions\n  - Osteochondritis dissecans\n\nUnit 8: Complex Injuries\n  - O'Donoghue's triad\n  - Segond fracture\n  - Pivot shift injuries\n  - Multi-ligament tears\n\nUnit 9: Arthroscopy Correlation\n  - 45+ surgical cases\n  - MRI-arthroscopy matching\n  - Diagnostic accuracy",
        "tags": ["MSK", "Sports", "Knee", "MRI"],
        "modality": "MRI",
        "body_regions": ["MSK"],
        "level": "Intermediate",
        "is_my_course": False,
        "is_downloaded": True
    },
    {
        "name": "Head CT in Trauma: Systematic Interpretation",
        "description": "Critical emergency imaging course for head CT interpretation in trauma patients. Learn systematic search patterns to avoid missing injuries, recognize all types of intracranial hemorrhage, identify skull fractures and facial trauma, and assess for brain herniation. Understand indications for neurosurgical intervention and how to communicate critical findings. Master the interpretation of epidural, subdural, subarachnoid, and intraparenchymal hemorrhages. Includes pediatric considerations and non-accidental trauma. 60+ cases from level 1 trauma center.",
        "author": "Dr. Jennifer Martinez, MD - Emergency Neuroradiology",
        "outline": "Lesson 1: Trauma CT Protocol\n  - Helical technique\n  - Bone and soft tissue windows\n  - When to add CTA\n  - Cervical spine inclusion\n\nLesson 2: Systematic Search Pattern\n  - Scalp and soft tissues\n  - Skull and skull base\n  - Extra-axial spaces\n  - Brain parenchyma\n  - Ventricles and cisterns\n  - CT checklist approach\n\nLesson 3: Epidural Hematoma\n  - Lentiform shape\n  - Arterial vs venous\n  - Skull fracture association\n  - Surgical indications\n  - Lucid interval\n\nLesson 4: Subdural Hematoma\n  - Crescentic shape\n  - Acute, subacute, chronic\n  - Midline shift measurement\n  - Mixed density (rebleed)\n\nLesson 5: Subarachnoid Hemorrhage\n  - Traumatic vs aneurysmal\n  - Distribution patterns\n  - Complications (vasospasm)\n  - When to perform CTA\n\nLesson 6: Intraparenchymal Injuries\n  - Contusions\n  - Diffuse axonal injury\n  - Brainstem injury\n  - Basal ganglia hemorrhage\n\nLesson 7: Skull and Facial Fractures\n  - Calvarial fractures\n  - Skull base fractures\n  - Pneumocephalus\n  - CSF leak signs\n  - Facial bone trauma\n\nLesson 8: Brain Herniation\n  - Subfalcine herniation\n  - Uncal herniation\n  - Tonsillar herniation\n  - Critical findings communication\n\nLesson 9: Pediatric Head Trauma\n  - Growing fractures\n  - Non-accidental trauma patterns\n  - Age-specific considerations\n\nLesson 10: Case Review\n  - 60+ trauma cases\n  - Subtle findings\n  - Multi-compartment injuries\n  - Outcome correlation",
        "tags": ["Trauma", "Emergency", "Neuro", "Critical"],
        "modality": "CT",
        "body_regions": ["Neuro"],
        "level": "Advanced",
        "is_my_course": True,
        "is_downloaded": True
    },
    {
        "name": "Shoulder MRI: Rotator Cuff Pathology",
        "description": "In-depth course on shoulder MRI for rotator cuff evaluation. Essential for MSK radiologists and orthopedic surgeons. Covers full-thickness and partial-thickness tears, tendinosis, impingement syndromes, and rotator cuff arthropathy. Learn surgical planning criteria, post-operative imaging, and common complications. Understand normal anatomy, variants, and systematic interpretation approach. 30+ surgical correlation cases.",
        "author": "Dr. Patricia Lee, MD - Shoulder Imaging Specialist",
        "outline": "Introduction: Shoulder MRI Technique\n  - Optimal patient positioning\n  - Sequence protocol\n  - Abduction vs adduction\n  - MR arthrography indications\n\nAnatomy Review\n  - Rotator cuff muscles and tendons\n  - Biceps tendon\n  - Labral anatomy\n  - Bursae and spaces\n\nRotator Cuff Tears\n  - Full-thickness tears\n  - Partial-thickness tears (articular vs bursal)\n  - Tear size and retraction\n  - Muscle atrophy and fatty infiltration\n  - Goutallier classification\n\nImpingement Syndromes\n  - Subacromial impingement\n  - Internal impingement\n  - Acromial morphology (Bigliani types)\n  - Os acromiale\n\nTendinosis and Calcific Tendinitis\n  - Tendinosis patterns\n  - Calcific tendinitis stages\n  - Treatment implications\n\nRotator Cuff Arthropathy\n  - Diagnostic criteria\n  - Acetabularization\n  - Surgical considerations\n\nPost-Operative Shoulder\n  - Normal post-op appearance\n  - Recurrent tears\n  - Hardware artifacts\n\nCase Studies\n  - 30+ surgical cases\n  - Pre- and post-op imaging",
        "tags": ["MSK", "Shoulder", "Rotator Cuff", "Sports"],
        "modality": "MRI",
        "body_regions": ["MSK"],
        "level": "Advanced",
        "is_my_course": False,
        "is_downloaded": False
    },
    {
        "name": "Liver MRI: Focal Lesion Characterization",
        "description": "Comprehensive liver MRI course focusing on focal lesion detection and characterization. Master the use of hepatobiliary contrast agents, diffusion-weighted imaging, and dynamic multi-phase imaging. Learn to differentiate benign from malignant lesions, recognize hepatocellular carcinoma, and understand LI-RADS reporting. Covers cirrhotic and non-cirrhotic livers, surveillance protocols, and treatment response assessment. 40+ pathology-proven cases.",
        "author": "Dr. Raymond Park, MD - Abdominal Imaging",
        "outline": "Part 1: Liver MRI Technique\n  - Sequence optimization\n  - Hepatobiliary contrast agents\n  - Dynamic phases (arterial, portal venous, delayed)\n  - DWI and ADC maps\n\nPart 2: Normal Liver Anatomy and Variants\n  - Segmental anatomy (Couinaud)\n  - Vascular anatomy\n  - Pseudo-lesions and artifacts\n  - Focal fat and focal sparing\n\nPart 3: Benign Liver Lesions\n  - Hemangiomas\n  - Focal nodular hyperplasia (FNH)\n  - Hepatic adenomas\n  - Simple cysts and complex cysts\n\nPart 4: Hepatocellular Carcinoma (HCC)\n  - Major and ancillary features\n  - Arterial phase hyperenhancement (APHE)\n  - Washout appearance\n  - Capsule enhancement\n  - Threshold growth\n\nPart 5: LI-RADS System\n  - LR-1 to LR-5 categories\n  - LR-M (malignancy, not HCC)\n  - LR-TIV (tumor in vein)\n  - Observation size categories\n\nPart 6: Metastases\n  - Hypervascular metastases\n  - Hypovascular metastases\n  - Diffusion restriction patterns\n\nPart 7: Cirrhosis and Surveillance\n  - Regenerative vs dysplastic nodules\n  - Surveillance protocols\n  - High-risk populations\n\nPart 8: Treatment Response\n  - TACE and ablation changes\n  - Viable tumor assessment\n  - mRECIST criteria\n\nPart 9: Case Library\n  - 40+ pathology-proven cases\n  - Challenging diagnoses",
        "tags": ["Liver", "Oncology", "HCC", "Advanced"],
        "modality": "MRI",
        "body_regions": ["Abdomen"],
        "level": "Advanced",
        "is_my_course": False,
        "is_downloaded": False
    },
    {
        "name": "Prostate MRI: PI-RADS v2.1 Essentials",
        "description": "Complete guide to multiparametric prostate MRI using PI-RADS v2.1 classification. Learn systematic interpretation combining T2-weighted, diffusion-weighted, and dynamic contrast-enhanced sequences. Understand zonal anatomy, recognize clinically significant cancer, and master sector-based reporting. Essential for radiologists performing prostate MRI and urologists using imaging for biopsy guidance. 35+ biopsy-correlated cases.",
        "author": "Dr. Steven Wright, MD - Genitourinary Imaging",
        "outline": "Chapter 1: Prostate MRI Protocol\n  - Patient preparation\n  - Coil selection (surface vs endorectal)\n  - T2WI, DWI, DCE sequences\n  - Field strength considerations\n\nChapter 2: Prostate Anatomy\n  - Zonal anatomy (PZ, TZ, CZ, AFS)\n  - 39-sector map\n  - Neurovascular bundles\n  - Seminal vesicles\n\nChapter 3: T2-Weighted Imaging\n  - Normal zonal appearance\n  - Peripheral zone assessment\n  - Transition zone patterns\n  - Benign prostatic hyperplasia (BPH)\n\nChapter 4: Diffusion-Weighted Imaging\n  - High b-value DWI (1400-2000)\n  - ADC map interpretation\n  - Restricted diffusion in cancer\n  - False positives\n\nChapter 5: Dynamic Contrast Enhancement\n  - Focal early enhancement\n  - Time-intensity curves\n  - When DCE affects scoring\n\nChapter 6: PI-RADS Scoring System\n  - Category 1-5 definitions\n  - Peripheral zone (DWI dominant)\n  - Transition zone (T2 dominant)\n  - Size thresholds (>15mm)\n  - EPE and invasion assessment\n\nChapter 7: Pitfalls and Artifacts\n  - Prostatitis and atrophy\n  - Post-biopsy hemorrhage\n  - BPH nodules\n  - Motion and susceptibility artifacts\n\nChapter 8: Clinical Integration\n  - Biopsy guidance (in-bore vs fusion)\n  - Active surveillance\n  - Post-treatment imaging\n\nChapter 9: Biopsy Correlation\n  - 35+ Gleason-graded cases\n  - PI-RADS accuracy\n  - Clinically significant cancer",
        "tags": ["Prostate", "PI-RADS", "Oncology", "GU"],
        "modality": "MRI",
        "body_regions": ["Pelvis"],
        "level": "Advanced",
        "is_my_course": True,
        "is_downloaded": False
    }
]


def clear_all_courses():
    """Delete all courses from database."""
    courses = get_all_courses()
    for course in courses:
        delete_course(course['course_pk'])
    print(f"Cleared {len(courses)} existing courses.")


def seed_comprehensive_samples(force=False):
    """
    Populate database with comprehensive sample courses for UI/UX evaluation.
    
    Args:
        force: If True, clear existing courses and reseed. If False, only seed if empty.
    """
    existing = get_all_courses()
    
    if existing and not force:
        print(f"Database already has {len(existing)} courses.")
        response = input("Clear and reseed with comprehensive samples? (y/n): ").strip().lower()
        if response != 'y':
            print("Skipping seed. Use --force or -f flag to force reseed.")
            return
        force = True
    
    if force and existing:
        print("\n[*] Clearing existing courses...")
        clear_all_courses()
        print()
    
    print("=" * 80)
    print("SEEDING COMPREHENSIVE SAMPLE COURSES FOR UI/UX EVALUATION")
    print("=" * 80)
    print()
    
    for i, course_data in enumerate(COMPREHENSIVE_COURSES, 1):
        course_id = insert_course(**course_data)
        
        # Status indicators
        status = "[Downloaded]" if course_data.get('is_downloaded') else "[Online Only]"
        ownership = "[My Course]" if course_data.get('is_my_course') else "[Library]"
        
        print(f"[{i:2d}/{len(COMPREHENSIVE_COURSES)}] {course_data['name']}")
        print(f"      Author: {course_data['author']}")
        print(f"      {course_data['modality']:12s} | {course_data['level']:12s} | {', '.join(course_data['body_regions'])}")
        print(f"      Tags: {', '.join(course_data['tags'][:4])}")
        print(f"      {status} | {ownership}")
        print(f"      Course ID: {course_id}")
        print()
    
    print("=" * 80)
    print(f"[SUCCESS] Seeded {len(COMPREHENSIVE_COURSES)} comprehensive courses!")
    print("=" * 80)
    print()
    
    # Statistics
    print("COURSE DISTRIBUTION:")
    print(f"   Library courses (not mine):  {sum(1 for c in COMPREHENSIVE_COURSES if not c.get('is_my_course', True)):2d}")
    print(f"   My Created courses:          {sum(1 for c in COMPREHENSIVE_COURSES if c.get('is_my_course', True)):2d}")
    print(f"   Downloaded courses:          {sum(1 for c in COMPREHENSIVE_COURSES if c.get('is_downloaded', False)):2d}")
    print()
    
    print("MODALITY BREAKDOWN:")
    modalities = {}
    for c in COMPREHENSIVE_COURSES:
        mod = c['modality']
        modalities[mod] = modalities.get(mod, 0) + 1
    for mod, count in sorted(modalities.items()):
        print(f"   {mod:15s}: {count:2d} courses")
    print()
    
    print("LEVEL DISTRIBUTION:")
    levels = {}
    for c in COMPREHENSIVE_COURSES:
        lvl = c['level']
        levels[lvl] = levels.get(lvl, 0) + 1
    for lvl, count in sorted(levels.items()):
        print(f"   {lvl:15s}: {count:2d} courses")
    print()
    
    print("=" * 80)
    print("UI/UX EVALUATION GUIDE:")
    print("   1. Open the Education Module (graduation cap icon)")
    print("   2. Navigate to Library tab - see all courses")
    print("   3. Test filters (Modality, Body Region, Level)")
    print("   4. Click course cards to see details panel")
    print("   5. Navigate to My Courses tab:")
    print("      - Switch to 'Created by Me' - see your courses")
    print("      - Switch to 'Downloaded' - see downloaded courses")
    print("   6. Navigate to Build Course tab - see empty form")
    print("=" * 80)
    print()
    print("[READY] Database is now ready for comprehensive UI/UX evaluation!")
    print()


if __name__ == "__main__":
    import sys
    force = '--force' in sys.argv or '-f' in sys.argv
    seed_comprehensive_samples(force=force)
