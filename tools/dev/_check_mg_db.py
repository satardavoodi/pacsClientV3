"""Check database for MG series photometric metadata."""
import sys
sys.path.insert(0, ".")
from database.core import get_db_connection

with get_db_connection() as conn:
    cur = conn.cursor()

    # Find studies matching this patient
    cur.execute("SELECT pk, study_uid, patient_fk FROM studies WHERE study_uid LIKE '%20260512%' LIMIT 5")
    studies = cur.fetchall()
    print("Studies:", studies)

    # Find series for this study
    for study in studies:
        study_pk = study[0]
        cur.execute("""
            SELECT s.pk, s.series_number, s.modality, s.series_description
            FROM series s WHERE s.study_fk = ?
        """, (study_pk,))
        series_list = cur.fetchall()
        print(f"\nSeries for study {study_pk}:")
        for sr in series_list:
            print(f"  series_pk={sr[0]} num={sr[1]} modality={sr[2]} desc={sr[3]}")

        # Find MG series (series 6 from folder name)
        cur.execute("""
            SELECT s.pk, s.series_number, s.modality
            FROM series s WHERE s.study_fk = ? AND s.modality = 'MG'
        """, (study_pk,))
        mg_series = cur.fetchall()
        print(f"  MG series: {mg_series}")

        # Get a sample instance from series 6
        cur.execute("""
            SELECT s.pk FROM series s WHERE s.study_fk = ? AND s.series_number = 6
        """, (study_pk,))
        row = cur.fetchone()
        if row:
            series_pk = row[0]
            cur.execute("""
                SELECT i.pk, i.instance_number, i.photometric_interpretation, i.window_width, i.window_center
                FROM instances i WHERE i.series_fk = ? LIMIT 5
            """, (series_pk,))
            instances = cur.fetchall()
            print(f"\n  Instances for series 6 (pk={series_pk}):")
            for inst in instances:
                print(f"    pk={inst[0]} num={inst[1]} photo={inst[2]} ww={inst[3]} wc={inst[4]}")
