from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Assembly, AssemblyItem


def list_assemblies(session: Session, query: str | None = None) -> list[Assembly]:
    # Eager-load items so the list page's item-count display doesn't lazy
    # load after the session (and thus session_scope's connection) closes.
    stmt = select(Assembly).options(selectinload(Assembly.items))
    if query:
        stmt = stmt.where(Assembly.assembly_name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Assembly.assembly_name)
    return list(session.scalars(stmt).all())


def get_assembly(session: Session, assembly_id: int) -> Assembly | None:
    stmt = (
        select(Assembly)
        .where(Assembly.assembly_id == assembly_id)
        .options(selectinload(Assembly.items).selectinload(AssemblyItem.product))
    )
    return session.scalars(stmt).first()


def create_assembly(
    session: Session,
    assembly_name: str,
    version_name: str | None = None,
    notes: str | None = None,
) -> Assembly:
    assembly = Assembly(assembly_name=assembly_name, version_name=version_name, notes=notes)
    session.add(assembly)
    session.commit()
    session.refresh(assembly)
    return assembly


def update_assembly(session: Session, assembly_id: int, **fields) -> Assembly | None:
    assembly = session.get(Assembly, assembly_id)
    if assembly is None:
        return None
    for key, value in fields.items():
        setattr(assembly, key, value)
    session.commit()
    session.refresh(assembly)
    return assembly


def get_assembly_item(session: Session, assembly_item_id: int) -> AssemblyItem | None:
    return session.get(AssemblyItem, assembly_item_id)


def add_assembly_item(
    session: Session, assembly_id: int, product_id: int, amount: int
) -> AssemblyItem:
    assembly_item = AssemblyItem(assembly_id=assembly_id, product_id=product_id, amount=amount)
    session.add(assembly_item)
    session.commit()
    session.refresh(assembly_item)
    return assembly_item


def update_assembly_item(session: Session, assembly_item_id: int, **fields) -> AssemblyItem | None:
    assembly_item = session.get(AssemblyItem, assembly_item_id)
    if assembly_item is None:
        return None
    for key, value in fields.items():
        setattr(assembly_item, key, value)
    session.commit()
    session.refresh(assembly_item)
    return assembly_item


def delete_assembly_item(session: Session, assembly_item_id: int) -> None:
    assembly_item = session.get(AssemblyItem, assembly_item_id)
    if assembly_item is not None:
        session.delete(assembly_item)
        session.commit()
