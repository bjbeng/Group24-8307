from __future__ import annotations
import json
import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth.deps import current_user, verify_csrf
from app.config import get_settings

router = APIRouter(prefix="/api/rules", tags=["rules"])

_DEFAULT_RULES = {
    "rule_set_id": "default",
    "C1_required_modules": ["岗位条件", "职责", "作业指引", "巡检", "操作规范", "应急", "培训"],
    "E1_engineer_per_km": 100,
    "E1_section_km_gas": 30,
    "E1_section_km_oil": 40,
    "C4_require_year_in_standard": True,
    "llm_text_model": "Qwen3-1.7B-Instruct",
}


def _get_db():
    s = get_settings()
    conn = sqlite3.connect(s.engine_db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rule_sets (
            rule_set_id TEXT PRIMARY KEY,
            config TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


class RuleSetBody(BaseModel):
    rule_set_id: str
    config: dict


@router.get("")
async def list_rules(user_id: str = Depends(current_user)) -> dict:
    db = _get_db()
    try:
        rows = db.execute("SELECT rule_set_id, config FROM rule_sets").fetchall()
    finally:
        db.close()
    rule_sets = [{"rule_set_id": r[0], "config": json.loads(r[1])} for r in rows]
    return {"rule_sets": rule_sets or [{"rule_set_id": "default", "config": _DEFAULT_RULES}]}


@router.post("", dependencies=[Depends(verify_csrf)])
async def create_rule_set(body: RuleSetBody, user_id: str = Depends(current_user)) -> dict:
    db = _get_db()
    try:
        db.execute("INSERT OR REPLACE INTO rule_sets (rule_set_id, config) VALUES (?,?)",
                   (body.rule_set_id, json.dumps(body.config, ensure_ascii=False)))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "rule_set_id": body.rule_set_id}


@router.get("/{rule_set_id}")
async def get_rule_set(rule_set_id: str, user_id: str = Depends(current_user)) -> dict:
    if rule_set_id == "default":
        return {"rule_set_id": "default", "config": _DEFAULT_RULES}
    db = _get_db()
    try:
        row = db.execute("SELECT config FROM rule_sets WHERE rule_set_id=?", (rule_set_id,)).fetchone()
    finally:
        db.close()
    if not row:
        raise HTTPException(404, f"规则集 {rule_set_id} 不存在")
    return {"rule_set_id": rule_set_id, "config": json.loads(row[0])}


@router.delete("/{rule_set_id}", dependencies=[Depends(verify_csrf)])
async def delete_rule_set(rule_set_id: str, user_id: str = Depends(current_user)) -> dict:
    if rule_set_id == "default":
        raise HTTPException(400, "不能删除默认规则集")
    db = _get_db()
    try:
        db.execute("DELETE FROM rule_sets WHERE rule_set_id=?", (rule_set_id,))
        db.commit()
    finally:
        db.close()
    return {"ok": True}
