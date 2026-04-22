import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    try:
        print("Checking seed data...")

        # ✅ If ANY user exists → skip everything (safe for production)
        existing = db.query(models.User).first()
        if existing:
            print("Data already exists, skipping seed.")
            return

        print("Seeding fresh data...")

        # 👇 ONLY runs first time (no delete needed)
        users = [
            models.User(
                full_name="Kunal Dhingra",
                email="kunal.dhingra@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Technology shared DWH",
                spoc_name="Nimish Valia",
                cost_code=3716
            ),
            models.User(
                full_name="Bharat Agroya",
                email="bharat.agroya@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Technology operations",
                spoc_name="Melwyn Dsouza",
                cost_code=3717
            ),
            models.User(
                full_name="Amit Goel",  # ✅ ADDED USER
                email="amit.goel@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Technology others",
                spoc_name="Amit Goel",
                cost_code=3722
            ),
            models.User(
                full_name="Shivani V",
                email="shivani.v@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Technology shared DWH",
                spoc_name="Somnath",
                cost_code=3716
            ),
            models.User(
                full_name="Manoj Nair",
                email="manoj.nair@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Treasury",
                spoc_name="Sreekanth",
                cost_code=3714
            ),
            models.User(
                full_name="Ravi Pichan",
                email="ravi.pichan@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Technology others",
                spoc_name="Amit Goel",
                cost_code=3722
            ),
            models.User(
                full_name="Pradip Nadkarni",
                email="pradip.nadkarni@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.IT_HEAD,
                department="Operation Technology",
                spoc_name="Sriram Krishnan",
                cost_code=3709
            ),
            models.User(
                full_name="Kavita Nair (CA)",
                email="kavita.nair@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.ADMIN,
                department="Finance"
            ),
            models.User(
                full_name="Vishwavir Ahuja",
                email="vishwavir.ahuja@rblbank.com",
                password=hash_password("Pass@1234"),
                role=models.UserRole.SUPER_ADMIN,
                department="Executive"
            ),
        ]

        db.add_all(users)
        db.commit()

        for u in users:
            db.refresh(u)

        # IDs
        kunal_id  = users[0].id
        bharat_id = users[1].id
        amit_id   = users[2].id
        kavita_id = users[-2].id
        ceo_id    = users[-1].id

        # Sample budget lines (same as yours)
        lines = [
            models.BudgetLine(
                budget_key_current="OFY2026_505",
                budget_key_previous="Old But Incremental",
                old_new=models.OldNew.OLD_BUT_INCREMENTAL,
                business_name="Technology shared DWH",
                cost_code=3716,
                submitted_by=kunal_id,
                it_head_name="Kunal Dhingra",
                spoc_name="Nimish Valia",
                expense_sub_type=models.ExpenseSubType.HARDWARE,
                description="DC2 hosting & power",
                expense_description="DC 2 Mahape year 2 Co Hosting charges",
                application_platform="DataCentre Support - Power Cost",
                budget_amt_current_fy=32200000,
                budget_amt_next_fy=35913480,
                diff_c_minus_a=3713480,
                detailed_reasoning="1st year budget carry forward.",
                status=models.BudgetStatus.SUBMITTED,
            ),
        ]

        db.add_all(lines)
        db.commit()

        # Approvals
        db.add(models.Approval(
            budget_line_id=lines[0].id,
            action_by=kavita_id,
            action=models.ApprovalAction.APPROVED,
            comment="Verified."
        ))

        db.commit()

        print("\n✅ Seed complete!")
        print("\nLogin credentials:")
        print("  IT Head  → amit.goel@rblbank.com / Pass@1234")

    finally:
        db.close()


if __name__ == "__main__":
    seed()