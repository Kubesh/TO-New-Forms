from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Category > subcategory > sub sub category (enforced in src/services/categories.py).
MAX_CATEGORY_DEPTH = 3


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=func.now(), nullable=False
    )


class CustomerType(Base, TimestampMixin):
    __tablename__ = "customer_types"

    customer_type_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(20))

    customers: Mapped[list["Customer"]] = relationship(back_populates="customer_type")


class OrderType(Base, TimestampMixin):
    __tablename__ = "order_types"

    order_type_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_types.customer_type_id")
    )
    default_order_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_types.order_type_id")
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("customers.customer_id"))
    store_key: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(100))
    phone_number: Mapped[str | None] = mapped_column(String(25))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    billing_address_line1: Mapped[str | None] = mapped_column(String(255))
    billing_address_line2: Mapped[str | None] = mapped_column(String(255))
    billing_city: Mapped[str | None] = mapped_column(String(120))
    billing_state: Mapped[str | None] = mapped_column(String(120))
    billing_postal_code: Mapped[str | None] = mapped_column(String(20))
    billing_country: Mapped[str | None] = mapped_column(String(120))

    shipping_address_line1: Mapped[str | None] = mapped_column(String(255))
    shipping_address_line2: Mapped[str | None] = mapped_column(String(255))
    shipping_city: Mapped[str | None] = mapped_column(String(120))
    shipping_state: Mapped[str | None] = mapped_column(String(120))
    shipping_postal_code: Mapped[str | None] = mapped_column(String(20))
    shipping_country: Mapped[str | None] = mapped_column(String(120))

    customer_type: Mapped["CustomerType | None"] = relationship(back_populates="customers")
    default_order_type: Mapped["OrderType | None"] = relationship()
    parent: Mapped["Customer | None"] = relationship(
        remote_side="Customer.customer_id", back_populates="children"
    )
    children: Mapped[list["Customer"]] = relationship(back_populates="parent")
    contacts: Mapped[list["CustomerContact"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class CustomerContact(Base, TimestampMixin):
    __tablename__ = "customer_contacts"

    contact_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=False
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped["Customer"] = relationship(back_populates="contacts")


class Item(Base, TimestampMixin):
    __tablename__ = "items"

    item_id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.category_id"))
    search_terms: Mapped[str | None] = mapped_column(Text)
    measured_in: Mapped[str | None] = mapped_column(String(50))
    unit_weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    sellable_content_weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    shopify_item_number: Mapped[str | None] = mapped_column(String(50))
    shopify_variant_number: Mapped[str | None] = mapped_column(String(50))
    sellable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    shipping_material: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    category: Mapped["Category | None"] = relationship()
    line_items: Mapped[list["PurchaseOrderLineItem"]] = relationship(back_populates="item")


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "po_headers"

    po_id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.customer_id"))
    store_key: Mapped[int | None] = mapped_column()
    order_type: Mapped[str | None] = mapped_column(String(50))
    order_date: Mapped[date | None] = mapped_column()
    due_date: Mapped[date | None] = mapped_column()
    requested_ship_date: Mapped[date | None] = mapped_column()
    # A timestamp (not just a date) so "Ship PO" can record the actual
    # moment it was marked shipped, not just the day.
    ship_date: Mapped[datetime | None] = mapped_column()
    order_entry_timestamp: Mapped[datetime | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    voided: Mapped[bool] = mapped_column(default=False, server_default="false")

    customer: Mapped["Customer | None"] = relationship()
    line_items: Mapped[list["PurchaseOrderLineItem"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )
    shipping_materials: Mapped[list["OrderShippingMaterial"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLineItem(Base, TimestampMixin):
    __tablename__ = "po_line_items"

    line_item_id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("po_headers.po_id"), nullable=False)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.item_id"))
    sku: Mapped[str | None] = mapped_column(String(50))
    item_description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    original_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    expanded_weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    box: Mapped[str | None] = mapped_column(String(50))
    shopify_item_number: Mapped[str | None] = mapped_column(String(50))
    # The per-case price this line was entered at (see ItemPrice), kept here so
    # a later price change doesn't rewrite an old PO. NULL for lines entered
    # before pricing existed, or for an item with no price yet.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    price_source: Mapped[str | None] = mapped_column(String(20))

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="line_items")
    item: Mapped["Item | None"] = relationship(back_populates="line_items")


class ItemPrice(Base, TimestampMixin):
    """A per-case price, for one item (a SKU) or for a category (a line or form
    factor - every item under it). Scope is a customer (their own price), a
    customer type (every customer of that type), or neither (the default)."""

    __tablename__ = "item_prices"

    item_price_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.item_id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.category_id", ondelete="CASCADE")
    )
    customer_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_types.customer_type_id", ondelete="CASCADE")
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE")
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)


class CategoryExclusion(Base, TimestampMixin):
    """A category (and everything under it) that isn't sold to a customer type
    or to a single customer."""

    __tablename__ = "category_exclusions"

    category_exclusion_id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.category_id", ondelete="CASCADE"), nullable=False
    )
    customer_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_types.customer_type_id", ondelete="CASCADE")
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE")
    )


class QboConnection(Base, TimestampMixin):
    """The authorised QuickBooks Online company. Tokens are rotated by Intuit
    on every refresh, so the latest ones must always be the ones saved."""

    __tablename__ = "qbo_connection"

    qbo_connection_id: Mapped[int] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    realm_id: Mapped[str] = mapped_column(String(40), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_expires_at: Mapped[datetime] = mapped_column(nullable=False)


class QboCustomerLink(Base, TimestampMixin):
    """An app customer's QuickBooks customer, in one QuickBooks company
    (realm). Keyed by realm so sandbox and real links can coexist."""

    __tablename__ = "qbo_customer_link"

    qbo_customer_link_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE"), nullable=False
    )
    realm_id: Mapped[str] = mapped_column(String(40), nullable=False)
    qbo_customer_id: Mapped[str] = mapped_column(String(40), nullable=False)
    qbo_display_name: Mapped[str | None] = mapped_column(String(255))


class QboItemLink(Base, TimestampMixin):
    """An app item's QuickBooks product/service, in one QuickBooks company."""

    __tablename__ = "qbo_item_link"

    qbo_item_link_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.item_id", ondelete="CASCADE"), nullable=False
    )
    realm_id: Mapped[str] = mapped_column(String(40), nullable=False)
    qbo_item_id: Mapped[str] = mapped_column(String(40), nullable=False)
    qbo_item_name: Mapped[str | None] = mapped_column(String(255))


class OrderShipstation(Base, TimestampMixin):
    """One row each time a PO is sent to ShipStation (so a PO can be sent
    more than once). label_created_at / tracking_number are filled in later
    by scripts/shipstation_sync.py once the label is printed in ShipStation -
    that is not the same as the order having physically shipped."""

    __tablename__ = "order_shipstation"

    order_shipstation_id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(
        ForeignKey("po_headers.po_id", ondelete="CASCADE"), nullable=False
    )
    shipstation_order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_key: Mapped[str] = mapped_column(String(100), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(50))
    sent_at: Mapped[datetime] = mapped_column(nullable=False)
    label_created_at: Mapped[datetime | None] = mapped_column()
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    carrier_code: Mapped[str | None] = mapped_column(String(50))
    last_checked_at: Mapped[datetime | None] = mapped_column()


class OrderShippingMaterial(Base, TimestampMixin):
    __tablename__ = "order_shipping_materials"

    order_shipping_material_id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("po_headers.po_id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="shipping_materials")
    item: Mapped["Item"] = relationship()


class Category(Base, TimestampMixin):
    """Categories, subcategories (lines) and sub sub categories all live in this one
    table - each is just a row whose parent_id points at its parent's row. color is only really meaningful for top-level rows
    (it drives the card-indicator color everywhere categories are shown)
    but isn't restricted at the schema level."""

    __tablename__ = "categories"

    category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.category_id"))
    color: Mapped[str | None] = mapped_column(String(20))

    # Eager (joined), so the whole ancestor chain is available after the
    # session closes, whichever way the Category itself was loaded.
    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.category_id",
        back_populates="subcategories",
        lazy="joined",
        # One past the top level, so a top-level row's own parent (None) is
        # loaded too rather than left to lazy-load after the session closes.
        join_depth=MAX_CATEGORY_DEPTH + 1,
    )
    subcategories: Mapped[list["Category"]] = relationship(back_populates="parent")


class InventoryCount(Base, TimestampMixin):
    """A single physical-count session. Deliberately minimal beyond the
    timestamps - kept separate from InventoryCountItem so more fields
    (who ran it, a location, a status) can be added later without
    touching the per-item rows."""

    __tablename__ = "inventory_counts"

    inventory_count_id: Mapped[int] = mapped_column(primary_key=True)

    items: Mapped[list["InventoryCountItem"]] = relationship(
        back_populates="inventory_count", cascade="all, delete-orphan"
    )


class InventoryCountItem(Base, TimestampMixin):
    """One item's counted quantity within an InventoryCount session. An
    item's "current on hand" is derived as whichever of these is most
    recent for that item, rather than a separate mutable total - so this
    table is the single source of truth, never out of sync with itself."""

    __tablename__ = "inventory_count_items"

    inventory_count_item_id: Mapped[int] = mapped_column(primary_key=True)
    inventory_count_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_counts.inventory_count_id"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    # A signed quantity, not necessarily whole - some counted items are
    # weight-based (e.g. 61.80342906 lbs).
    counted: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    inventory_count: Mapped["InventoryCount"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()


class Assembly(Base, TimestampMixin):
    """A named recipe that converts some items into others in a batch - e.g.
    breaking bulk soil down into bagged units, or combining components into
    a kit. The actual item-level effects (what's consumed, what's produced)
    live on its versions, not here - an assembly can be revised over time
    (a new version_name) without losing the history of earlier ones."""

    __tablename__ = "assemblies"

    assembly_id: Mapped[int] = mapped_column(primary_key=True)
    assembly_name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # The one version currently in use - always one of this assembly's own
    # versions (enforced in the service layer, not the schema), never a
    # version under a different assembly.
    active_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("assembly_versions.assembly_version_id")
    )

    versions: Mapped[list["AssemblyVersion"]] = relationship(
        back_populates="assembly",
        cascade="all, delete-orphan",
        foreign_keys="AssemblyVersion.assembly_id",
    )
    active_version: Mapped["AssemblyVersion | None"] = relationship(
        foreign_keys=[active_version_id]
    )


class AssemblyVersion(Base, TimestampMixin):
    """One revision of an assembly's recipe - its own notes plus the set of
    items it consumes/produces (AssemblyVersionItem), independent of any
    other version under the same assembly. replaces_version_id tracks
    lineage across a discontinued version to whichever version took over
    for it - not restricted to the same assembly, so a version can also
    record that it took over for a version under a different assembly
    entirely (e.g. two recipes merged into one)."""

    __tablename__ = "assembly_versions"

    assembly_version_id: Mapped[int] = mapped_column(primary_key=True)
    assembly_id: Mapped[int] = mapped_column(ForeignKey("assemblies.assembly_id"), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    replaces_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("assembly_versions.assembly_version_id")
    )

    assembly: Mapped["Assembly"] = relationship(
        back_populates="versions", foreign_keys=[assembly_id]
    )
    items: Mapped[list["AssemblyVersionItem"]] = relationship(
        back_populates="assembly_version", cascade="all, delete-orphan"
    )
    replaces: Mapped["AssemblyVersion | None"] = relationship(
        remote_side="AssemblyVersion.assembly_version_id", back_populates="replaced_by"
    )
    replaced_by: Mapped[list["AssemblyVersion"]] = relationship(back_populates="replaces")


class AssemblyVersionItem(Base, TimestampMixin):
    """One product's role in an assembly version - amount is negative for a
    product consumed by it, positive for a product it produces."""

    __tablename__ = "assembly_version_items"

    assembly_version_item_id: Mapped[int] = mapped_column(primary_key=True)
    assembly_version_id: Mapped[int] = mapped_column(
        ForeignKey("assembly_versions.assembly_version_id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    # A signed quantity, not necessarily a whole number - recipe amounts
    # (e.g. 26.20 parts per batch) are fractional.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    assembly_version: Mapped["AssemblyVersion"] = relationship(back_populates="items")
    product: Mapped["Item"] = relationship()


class Batch(Base, TimestampMixin):
    """One production run of an assembly version - parent_id lets a batch
    trace back to whichever batch it was produced from (e.g. splitting one
    batch's output into further batches), independent of its own version's
    lineage. released_at is null while the batch is still being worked on;
    setting it marks the batch done."""

    __tablename__ = "batches"

    batch_id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("assembly_versions.assembly_version_id"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("batches.batch_id"))
    released_at: Mapped[datetime | None] = mapped_column()
    batch_code: Mapped[str] = mapped_column(String(100), nullable=False)
    expire_date: Mapped[date | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    version: Mapped["AssemblyVersion"] = relationship()
    parent: Mapped["Batch | None"] = relationship(remote_side="Batch.batch_id", back_populates="children")
    children: Mapped[list["Batch"]] = relationship(back_populates="parent")
    items: Mapped[list["BatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BatchItem(Base, TimestampMixin):
    """One product's movement within a batch - units is negative for a
    product consumed by it, positive for a product it produces."""

    __tablename__ = "batch_items"

    batch_item_id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.batch_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    units: Mapped[float] = mapped_column(Float, nullable=False)
    lot_number: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    batch: Mapped["Batch"] = relationship(back_populates="items")
    product: Mapped["Item"] = relationship()
