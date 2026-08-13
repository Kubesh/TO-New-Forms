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
    category: Mapped[str | None] = mapped_column(String(100))
    subcategory: Mapped[str | None] = mapped_column(String(100))
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
    ship_date: Mapped[date | None] = mapped_column()
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
