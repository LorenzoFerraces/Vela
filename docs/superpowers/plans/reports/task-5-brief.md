### Task 5: DB migration for `build_override`

**Files:**
- Modify: `backend/app/db/models.py` — `StackService.build_override`, `DeploymentRecord.build_override`
- Create: `backend/alembic/versions/0016_build_override.py`

**Interfaces:**
- Produces: nullable JSON columns defaulting to `None`

- [ ] **Step 1: Add columns to models**

```python
build_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

on both `StackService` and `DeploymentRecord`.

- [ ] **Step 2: Alembic revision**

```python
revision = "0016_build_override"
down_revision = "0015_stack_service_git_branch"

def upgrade() -> None:
    op.add_column("stack_services", sa.Column("build_override", sa.JSON(), nullable=True))
    op.add_column("deployment_records", sa.Column("build_override", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("deployment_records", "build_override")
    op.drop_column("stack_services", "build_override")
```

NOTE: `0015_stack_service_git_branch.py` may still be untracked in the working tree — include it in the commit IF needed for the revision chain, or ensure 0015 is already committed. Check `git log` / alembic heads. If 0015 is untracked, stage and commit 0015 first (or in the same commit as 0016) so down_revision resolves.

- [ ] **Step 3: `alembic upgrade head` locally against dev DB** (from backend/, using venv python -m alembic)

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: persist build_override on stacks and deployment records"
```

IMPORTANT: `models.py` may have other uncommitted WIP (git_branch etc.). Stage carefully — only build_override column additions for this task, OR include git_branch if it's part of the same unfinished migration story already on the branch. Prefer minimal: only add build_override lines if git_branch already committed; if git_branch is only in working tree with 0015 untracked, commit 0015+git_branch model + 0016+build_override together as the persistence foundation.
