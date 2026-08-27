from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from src.models import Assembly, AssemblyVersion, AssemblyVersionItem, Batch


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
        .options(
            selectinload(Assembly.versions).selectinload(AssemblyVersion.items),
            selectinload(Assembly.versions)
            .selectinload(AssemblyVersion.replaces)
            .selectinload(AssemblyVersion.assembly),
            selectinload(Assembly.versions)
            .selectinload(AssemblyVersion.replaced_by)
            .selectinload(AssemblyVersion.assembly),
        )
    )
    return session.scalars(stmt).first()


def set_active_version(
    session: Session, assembly_id: int, assembly_version_id: int | None
) -> str | None:
    """Marks one version as the assembly's active one (or clears it, if
    assembly_version_id is None) - only one version can be active per
    assembly at a time, so this simply overwrites whatever was active
    before. Returns an error message on failure, None on success."""
    assembly = session.get(Assembly, assembly_id)
    if assembly is None:
        return "Assembly not found."
    if assembly_version_id is not None:
        version = session.get(AssemblyVersion, assembly_version_id)
        if version is None or version.assembly_id != assembly_id:
            return "That version doesn't belong to this assembly."
    assembly.active_version_id = assembly_version_id
    session.commit()
    return None


def delete_assembly(session: Session, assembly_id: int) -> str | None:
    """Deletes the assembly and all its versions/items. Refuses if any of
    its versions have batches recorded against them - those must be dealt
    with first, rather than silently orphaning a batch's version_id.
    Returns an error message on failure, None on success."""
    assembly = session.get(Assembly, assembly_id)
    if assembly is None:
        return "Assembly not found."

    version_ids = [v.assembly_version_id for v in assembly.versions]
    if version_ids:
        batch_count = session.scalar(
            select(func.count()).select_from(Batch).where(Batch.version_id.in_(version_ids))
        )
        if batch_count:
            return f"Can't delete - {batch_count} batch{'es' if batch_count != 1 else ''} reference this assembly's versions."
        session.execute(
            update(AssemblyVersion)
            .where(AssemblyVersion.replaces_version_id.in_(version_ids))
            .values(replaces_version_id=None)
        )

    assembly.active_version_id = None
    session.delete(assembly)
    session.commit()
    return None


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
            selectinload(AssemblyVersion.replaces).selectinload(AssemblyVersion.assembly),
        )
    )
    return session.scalars(stmt).first()


def list_all_version_choices(
    session: Session, exclude_version_id: int | None = None
) -> list[tuple[int, str, str]]:
    """(assembly_version_id, assembly_name, version_name) for every version
    across every assembly - for the "replaces" picker, which deliberately
    isn't scoped to one assembly (a version can take over for a version
    under a different assembly)."""
    stmt = (
        select(AssemblyVersion)
        .join(Assembly)
        .options(selectinload(AssemblyVersion.assembly))
        .order_by(Assembly.assembly_name, AssemblyVersion.version_name)
    )
    if exclude_version_id is not None:
        stmt = stmt.where(AssemblyVersion.assembly_version_id != exclude_version_id)
    versions = session.scalars(stmt).all()
    return [(v.assembly_version_id, v.assembly.assembly_name, v.version_name) for v in versions]


def create_version(
    session: Session,
    assembly_id: int,
    version_name: str,
    notes: str | None = None,
    replaces_version_id: int | None = None,
) -> AssemblyVersion:
    version = AssemblyVersion(
        assembly_id=assembly_id,
        version_name=version_name,
        notes=notes,
        replaces_version_id=replaces_version_id,
    )
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


def delete_version(session: Session, assembly_version_id: int) -> str | None:
    """Deletes one version and its items. Refuses if any batches reference
    it. Any other version that listed this one as replaces_version_id is
    unlinked (set to null) rather than blocking the delete - the lineage
    chain just loses that one link."""
    version = session.get(AssemblyVersion, assembly_version_id)
    if version is None:
        return "Version not found."

    batch_count = session.scalar(
        select(func.count()).select_from(Batch).where(Batch.version_id == assembly_version_id)
    )
    if batch_count:
        return f"Can't delete - {batch_count} batch{'es' if batch_count != 1 else ''} reference this version."

    session.execute(
        update(AssemblyVersion)
        .where(AssemblyVersion.replaces_version_id == assembly_version_id)
        .values(replaces_version_id=None)
    )
    session.execute(
        update(Assembly)
        .where(Assembly.active_version_id == assembly_version_id)
        .values(active_version_id=None)
    )
    session.delete(version)
    session.commit()
    return None


def get_descendant_version_ids(session: Session, assembly_version_id: int) -> set[int]:
    """Every version reachable by following replaced_by forward from this
    one - used to keep the "replaces" picker from letting a version point
    at something already downstream of itself, which would create a
    lineage cycle."""
    version = session.get(AssemblyVersion, assembly_version_id)
    if version is None:
        return set()
    ids: set[int] = set()
    stack = list(version.replaced_by)
    while stack:
        current = stack.pop()
        if current.assembly_version_id in ids:
            continue
        ids.add(current.assembly_version_id)
        stack.extend(current.replaced_by)
    return ids


def _version_node(version: AssemblyVersion) -> dict:
    return {
        "assembly_version_id": version.assembly_version_id,
        "assembly_id": version.assembly_id,
        "assembly_name": version.assembly.assembly_name,
        "version_name": version.version_name,
    }


def get_lineage_chains(session: Session, assembly_id: int) -> list[list[dict]]:
    """Every distinct replace-chain (oldest to newest) touching one of this
    assembly's versions, as plain dicts (safe to use after the session
    closes) - a chain can span other assemblies too, since
    replaces_version_id isn't scoped to one assembly. Versions with no
    replace link at all are omitted; branching (more than one version
    claiming to replace the same predecessor) yields one chain per branch."""
    assembly = session.get(Assembly, assembly_id)
    if assembly is None:
        return []

    def walk_to_root(version: AssemblyVersion) -> AssemblyVersion:
        seen = {version.assembly_version_id}
        while version.replaces is not None and version.replaces.assembly_version_id not in seen:
            version = version.replaces
            seen.add(version.assembly_version_id)
        return version

    def paths_from(version: AssemblyVersion, seen: set[int]) -> list[list[AssemblyVersion]]:
        seen = seen | {version.assembly_version_id}
        successors = [v for v in version.replaced_by if v.assembly_version_id not in seen]
        if not successors:
            return [[version]]
        paths = []
        for nxt in successors:
            for sub in paths_from(nxt, seen):
                paths.append([version] + sub)
        return paths

    roots_seen: set[int] = set()
    chains: list[list[dict]] = []
    for version in assembly.versions:
        if version.replaces is None and not version.replaced_by:
            continue
        root = walk_to_root(version)
        if root.assembly_version_id in roots_seen:
            continue
        roots_seen.add(root.assembly_version_id)
        for path in paths_from(root, set()):
            chains.append([_version_node(v) for v in path])
    return chains


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
