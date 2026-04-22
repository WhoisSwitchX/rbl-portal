import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def seed():
    print("Seeding demo data...")
    db.query(models.Approval).delete()
    db.query(models.BudgetLine).delete()
    db.query(models.UploadedFile).delete()
    db.query(models.Dummy2).delete()
    db.query(models.Dummy1).delete()
    db.query(models.User).delete()
    db.commit()

    users = [
        models.User(full_name="Kunal Dhingra",   email="kunal.dhingra@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Technology shared DWH", spoc_name="Nimish Valia", cost_code=3716),
        models.User(full_name="Bharat Agroya",   email="bharat.agroya@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Technology operations", spoc_name="Melwyn Dsouza", cost_code=3717),
        models.User(full_name="Shivani V",        email="shivani.v@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Technology shared DWH", spoc_name="Somnath", cost_code=3716),
        models.User(full_name="Manoj Nair",       email="manoj.nair@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Treasury", spoc_name="Sreekanth", cost_code=3714),
        models.User(full_name="Ravi Pichan",      email="ravi.pichan@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Technology others", spoc_name="Amit Goel", cost_code=3722),
        models.User(full_name="Pradip Nadkarni",  email="pradip.nadkarni@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.IT_HEAD,
                    department="Operation Technology", spoc_name="Sriram Krishnan", cost_code=3709),
        models.User(full_name="Kavita Nair (CA)", email="kavita.nair@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.ADMIN,
                    department="Finance"),
        models.User(full_name="Vishwavir Ahuja",  email="vishwavir.ahuja@rblbank.com",
                    password=hash_password("Pass@1234"), role=models.UserRole.SUPER_ADMIN,
                    department="Executive"),
    ]
    for u in users:
        db.add(u)
    db.commit()
    for u in users:
        db.refresh(u)

    kunal_id  = users[0].id
    bharat_id = users[1].id
    kavita_id = users[6].id
    ceo_id    = users[7].id

    lines = [
        models.BudgetLine(
            budget_key_current="OFY2026_505", budget_key_previous="Old But Incremental",
            old_new=models.OldNew.OLD_BUT_INCREMENTAL, business_name="Technology shared DWH",
            cost_code=3716, submitted_by=kunal_id, it_head_name="Kunal Dhingra", spoc_name="Nimish Valia",
            expense_sub_type=models.ExpenseSubType.HARDWARE,
            description="DC2 hosting & power", expense_description="DC 2 Mahape year 2 Co Hosting charges",
            application_platform="DataCentre Support - Power Cost",
            budget_amt_current_fy=32200000, projected_consumption=None, budget_amt_next_fy=35913480,
            diff_a_minus_b=None, diff_c_minus_b=None, diff_c_minus_a=3713480,
            detailed_reasoning="1st year budget carry forward. NTT invoicing delayed.",
            status=models.BudgetStatus.SUBMITTED,
        ),
        models.BudgetLine(
            budget_key_current="OFY2026_345", budget_key_previous="OFY2025_345, OFY2025_348",
            old_new=models.OldNew.OLD, business_name="Technology operations",
            cost_code=3717, submitted_by=bharat_id, it_head_name="Bharat Agroya", spoc_name="Melwyn Dsouza",
            expense_sub_type=models.ExpenseSubType.MANAGED,
            description="Managed Services for SAS", expense_description="RTB for FY26-27 for SAS",
            application_platform="SAS", vendor_name="SAS",
            budget_amt_current_fy=37632000, projected_consumption=8400000, budget_amt_next_fy=11344000,
            diff_a_minus_b=29232000, diff_c_minus_b=2944000, diff_c_minus_a=-26288000,
            detailed_reasoning="New Partner will be PwC",
            status=models.BudgetStatus.ADMIN_APPROVED,
        ),
        models.BudgetLine(
            budget_key_current="OFY2026_653", budget_key_previous="OFY2025_653",
            old_new=models.OldNew.OLD_BUT_INCREMENTAL, business_name="Technology operations",
            cost_code=3717, submitted_by=bharat_id, it_head_name="Bharat Agroya", spoc_name="Melwyn Dsouza",
            expense_sub_type=models.ExpenseSubType.TM_SERVICES,
            description="RTB FTC Resource - Accenture", expense_description="Application Support L1 & L2",
            application_platform="All apps in scope of Accenture", vendor_name="Accenture Solutions Pvt Ltd",
            resource_count=35,
            budget_amt_current_fy=108232640, projected_consumption=94160000, budget_amt_next_fy=95665600,
            diff_a_minus_b=14072640, diff_c_minus_b=1505600, diff_c_minus_a=-12567040,
            detailed_reasoning="12% escalation. Resource reduced from 41 to 35.",
            status=models.BudgetStatus.FINAL_APPROVED,
        ),
        models.BudgetLine(
            budget_key_current="OFY2026_028", budget_key_previous="OFY2025_028",
            old_new=models.OldNew.OLD, business_name="Treasury",
            cost_code=3714, submitted_by=users[3].id, it_head_name="Manoj Nair", spoc_name="Sreekanth",
            expense_sub_type=models.ExpenseSubType.SUBSCRIPTION,
            description="Metagrid Software Renewal", application_platform="Metagrid",
            vendor_name="Global Scape",
            budget_amt_current_fy=20500000, projected_consumption=4646016, budget_amt_next_fy=3491250,
            diff_a_minus_b=15853984, diff_c_minus_b=-1154766, diff_c_minus_a=-17008750,
            detailed_reasoning="16 months payment period vs 12 months.",
            status=models.BudgetStatus.DRAFT,
        ),
        models.BudgetLine(
            budget_key_current="OFY2026_697", budget_key_previous="Old",
            old_new=models.OldNew.OLD, business_name="Operation Technology",
            cost_code=3709, submitted_by=users[5].id, it_head_name="Pradip Nadkarni", spoc_name="Sriram Krishnan",
            expense_sub_type=models.ExpenseSubType.COMPLIANCE,
            description="Outsystems DR License", application_platform="Outsystems",
            budget_amt_current_fy=10000000, projected_consumption=0, budget_amt_next_fy=5350000,
            diff_a_minus_b=10000000, diff_c_minus_b=5350000, diff_c_minus_a=-4650000,
            detailed_reasoning="DR License USD 58,000 @ Rs 92/USD. No dedicated DR last year.",
            status=models.BudgetStatus.SUBMITTED,
        ),
    ]
    for l in lines:
        db.add(l)
    db.commit()
    for l in lines:
        db.refresh(l)

    db.add(models.Approval(budget_line_id=lines[1].id, action_by=kavita_id, action=models.ApprovalAction.APPROVED, comment="Verified. Forwarding to CEO."))
    db.add(models.Approval(budget_line_id=lines[2].id, action_by=kavita_id, action=models.ApprovalAction.APPROVED, comment="Verified."))
    db.add(models.Approval(budget_line_id=lines[2].id, action_by=ceo_id,    action=models.ApprovalAction.APPROVED, comment="Approved."))
    db.commit()

    print("\n✅ Seed complete!")
    print("\nLogin credentials:")
    print("  IT Head  → kunal.dhingra@rblbank.com   / Pass@1234")
    print("  IT Head  → bharat.agroya@rblbank.com   / Pass@1234")
    print("  IT Head  → manoj.nair@rblbank.com      / Pass@1234")
    print("  Admin CA → kavita.nair@rblbank.com     / Pass@1234")
    print("  CEO      → vishwavir.ahuja@rblbank.com / Pass@1234")

if __name__ == "__main__":
    try:
        seed()
    finally:
        db.close()
