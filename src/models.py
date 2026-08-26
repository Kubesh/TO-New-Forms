from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


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

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="line_items")
    item: Mapped["Item | None"] = relationship(back_populates="line_items")


class OrderShippingMaterial(Base, TimestampMixin):
    __tablename__ = "order_shipping_materials"

    order_shipping_material_id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("po_headers.po_id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="shipping_materials")
    item: Mapped["Item"] = relationship()


class Category(Base, TimestampMixin):
    """Both top-level categories and subcategories live in this one table -
    a subcategory is just a row whose parent_id points at its parent
    category's row. color is only really meaningful for top-level rows
    (it drives the card-indicator color everywhere categories are shown)
    but isn't restricted at the schema level."""

    __tablename__ = "categories"

    category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.category_id"))
    color: Mapped[str | None] = mapped_column(String(20))

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.category_id", back_populates="subcategories"
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
    counted: Mapped[int] = mapped_column(Integer, nullable=False)
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

    versions: Mapped[list["AssemblyVersion"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan"
    )


class AssemblyVersion(Base, TimestampMixin):
    """One revision of an assembly's recipe - its own notes plus the set of
    items it consumes/produces (AssemblyVersionItem), independent of any
    other version under the same assembly."""

    __tablename__ = "assembly_versions"

    assembly_version_id: Mapped[int] = mapped_column(primary_key=True)
    assembly_id: Mapped[int] = mapped_column(ForeignKey("assemblies.assembly_id"), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    assembly: Mapped["Assembly"] = relationship(back_populates="versions")
    items: Mapped[list["AssemblyVersionItem"]] = relationship(
        back_populates="assembly_version", cascade="all, delete-orphan"
    )


class AssemblyVersionItem(Base, TimestampMixin):
    """One product's role in an assembly version - amount is negative for a
    product consumed by it, positive for a product it produces."""

    __tablename__ = "assembly_version_items"

    assembly_version_item_id: Mapped[int] = mapped_column(primary_key=True)
    assembly_version_id: Mapped[int] = mapped_column(
        ForeignKey("assembly_versions.assembly_version_id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    assembly_version: Mapped["AssemblyVersion"] = relationship(back_populates="items")
    product: Mapped["Item"] = relationship()
