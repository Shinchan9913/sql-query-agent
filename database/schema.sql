-- Sample schema for the SQL Query Agent.
-- A small company database: HR (Departments, Employees) and sales
-- (Customers, Products, Orders, OrderItems).

PRAGMA foreign_keys = ON;

CREATE TABLE Departments (
    DepartmentID   INTEGER PRIMARY KEY,
    Name           TEXT    NOT NULL UNIQUE,
    Location       TEXT    NOT NULL,
    Budget         REAL    NOT NULL
);

CREATE TABLE Employees (
    EmployeeID     INTEGER PRIMARY KEY,
    FirstName      TEXT    NOT NULL,
    LastName       TEXT    NOT NULL,
    Email          TEXT    NOT NULL UNIQUE,
    JobTitle       TEXT    NOT NULL,
    DepartmentID   INTEGER NOT NULL REFERENCES Departments(DepartmentID),
    ManagerID      INTEGER REFERENCES Employees(EmployeeID),
    HireDate       DATE    NOT NULL,
    Salary         REAL    NOT NULL
);

CREATE TABLE Customers (
    CustomerID     INTEGER PRIMARY KEY,
    FirstName      TEXT    NOT NULL,
    LastName       TEXT    NOT NULL,
    Email          TEXT    NOT NULL UNIQUE,
    City           TEXT    NOT NULL,
    State          TEXT    NOT NULL,   -- full state name, e.g. 'California'
    Country        TEXT    NOT NULL DEFAULT 'USA',
    CreatedAt      DATE    NOT NULL
);

CREATE TABLE Products (
    ProductID      INTEGER PRIMARY KEY,
    Name           TEXT    NOT NULL,
    Category       TEXT    NOT NULL,
    UnitPrice      REAL    NOT NULL,
    StockQuantity  INTEGER NOT NULL
);

CREATE TABLE Orders (
    OrderID        INTEGER PRIMARY KEY,
    CustomerID     INTEGER NOT NULL REFERENCES Customers(CustomerID),
    EmployeeID     INTEGER REFERENCES Employees(EmployeeID),  -- sales rep
    OrderDate      DATE    NOT NULL,
    Status         TEXT    NOT NULL CHECK (Status IN ('Pending', 'Shipped', 'Delivered', 'Cancelled')),
    TotalAmount    REAL    NOT NULL
);

CREATE TABLE OrderItems (
    OrderItemID    INTEGER PRIMARY KEY,
    OrderID        INTEGER NOT NULL REFERENCES Orders(OrderID),
    ProductID      INTEGER NOT NULL REFERENCES Products(ProductID),
    Quantity       INTEGER NOT NULL,
    UnitPrice      REAL    NOT NULL
);

CREATE INDEX idx_employees_department ON Employees(DepartmentID);
CREATE INDEX idx_orders_customer      ON Orders(CustomerID);
CREATE INDEX idx_orderitems_order     ON OrderItems(OrderID);
