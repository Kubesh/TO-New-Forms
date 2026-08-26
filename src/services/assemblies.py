from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Assembly, AssemblyVersion, AssemblyVersionItem


def list_assemblies(session: Session, query: str | None = None) -> list[Assembly]:
    # Eager-load versions so the list page's version-count display doesn't
    # lazy load after the session (and thus session_scope's connection)
    # closes.
    stmt = select(Assembly).options(selectinload(Assembly.versions))
    if query:
        stmt = stmt.where(Assembly.assembly_name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Assembly.assembly_name)
    return list(session.scalars(stmt).all())


def get_assembly(session: Session, assembly_id: int) -> Assembly | None:
    stmt = (
        select(Assembly)
        .where(Assembly.assembly_id == assembly_id)
        .options(selectinload(Assembly.versions).selectinload(AssemblyVersion.items))
    )
    return session.scalars(stmt).first()


def create_assembly(session: Session, assembly_name: str, notes: str | None = None) -> Assembly:
    assembly = Assembly(assembly_name=assembly_name, notes=notes)
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


def get_version(session: Session, assembly_version_id: int) -> AssemblyVersion | None:
    stmt = (
        select(AssemblyVersion)
        .where(AssemblyVersion.assembly_version_id == assembly_version_id)
        .options(
            selectinload(AssemblyVersion.assembly),
            selectinload(AssemblyVersion.items).selectinload(AssemblyVersionItem.product),
        )
    )
    return session.scalars(stmt).first()


def create_version(
    session: Session, assembly_id: int, version_name: str, notes: str | None = None
) -> AssemblyVersion:
    version = AssemblyVersion(assembly_id=assembly_id, version_name=version_name, notes=notes)
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def update_version(session: Session, assembly_version_id: int, **fields) -> AssemblyVersion | None:
    version = session.get(AssemblyVersion, assembly_version_id)
    if version is None:
        return None
    for key, value in fields.items():
        setattr(version, key, value)
    session.commit()
    session.refresh(version)
    return version


def get_version_item(session: Session, assembly_version_item_id: int) -> AssemblyVersionItem | None:
    return session.get(AssemblyVersionItem, assembly_version_item_id)


def add_version_item(
    session: Session, assembly_version_id: int, product_id: int, amount: int
) -> AssemblyVersionItem:
    version_item = AssemblyVersionItem(
        assembly_version_id=assembly_version_id, product_id=product_id, amount=amount
    )
    session.add(version_item)
    session.commit()
    session.refresh(version_item)
    return version_item


def update_version_item(
    session: Session, assembly_version_item_id: int, **fields
) -> AssemblyVersionItem | None:
    version_item = session.get(AssemblyVersionItem, assembly_version_item_id)
    if version_item is None:
        return None
    for key, value in fields.items():
        setattr(version_item, key, value)
    session.commit()
    session.refresh(version_item)
    return version_item


def delete_version_item(session: Session, assembly_version_item_id: int) -> None:
    version_item = session.get(AssemblyVersionItem, assembly_version_item_id)
    if version_item is not None:
        session.delete(version_item)
        session.commit()
