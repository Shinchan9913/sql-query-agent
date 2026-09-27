-- Seed data for the sample schema.

INSERT INTO Departments (DepartmentID, Name, Location, Budget) VALUES
    (1, 'Engineering', 'San Francisco', 1500000),
    (2, 'Sales',       'New York',       800000),
    (3, 'Marketing',   'Austin',         500000),
    (4, 'HR',          'Chicago',        300000),
    (5, 'Finance',     'New York',       450000);

INSERT INTO Employees (EmployeeID, FirstName, LastName, Email, JobTitle, DepartmentID, ManagerID, HireDate, Salary) VALUES
    (1,  'Alice',   'Nguyen',   'alice.nguyen@acme.com',   'VP of Engineering',   1, NULL, '2019-03-15', 210000),
    (2,  'Bob',     'Martinez', 'bob.martinez@acme.com',   'Sales Director',      2, NULL, '2018-07-01', 180000),
    (3,  'Carol',   'Smith',    'carol.smith@acme.com',    'Marketing Manager',   3, NULL, '2020-01-10', 140000),
    (4,  'David',   'Kim',      'david.kim@acme.com',      'HR Manager',          4, NULL, '2021-05-20', 120000),
    (5,  'Eva',     'Brown',    'eva.brown@acme.com',      'Finance Manager',     5, NULL, '2019-11-03', 150000),
    (6,  'Frank',   'Lee',      'frank.lee@acme.com',      'Senior Engineer',     1, 1,    '2022-02-14', 165000),
    (7,  'Grace',   'Patel',    'grace.patel@acme.com',    'Software Engineer',   1, 6,    '2024-01-08', 125000),
    (8,  'Henry',   'Wilson',   'henry.wilson@acme.com',   'Software Engineer',   1, 6,    '2024-06-17', 120000),
    (9,  'Isabel',  'Garcia',   'isabel.garcia@acme.com',  'Account Executive',   2, 2,    '2023-09-05', 95000),
    (10, 'Jack',    'Thompson', 'jack.thompson@acme.com',  'Account Executive',   2, 2,    '2024-03-11', 90000),
    (11, 'Karen',   'White',    'karen.white@acme.com',    'Content Strategist',  3, 3,    '2023-04-22', 85000),
    (12, 'Leo',     'Harris',   'leo.harris@acme.com',     'Recruiter',           4, 4,    '2024-08-01', 75000),
    (13, 'Maya',    'Clark',    'maya.clark@acme.com',     'Financial Analyst',   5, 5,    '2022-10-12', 98000),
    (14, 'Noah',    'Lewis',    'noah.lewis@acme.com',     'Data Engineer',       1, 1,    '2025-01-06', 135000),
    (15, 'Olivia',  'Walker',   'olivia.walker@acme.com',  'Sales Associate',     2, 2,    '2025-02-18', 70000);

INSERT INTO Customers (CustomerID, FirstName, LastName, Email, City, State, Country, CreatedAt) VALUES
    (1,  'Liam',     'Johnson',  'liam.j@example.com',     'Los Angeles',   'California', 'USA', '2023-01-12'),
    (2,  'Emma',     'Davis',    'emma.d@example.com',     'San Diego',     'California', 'USA', '2023-03-08'),
    (3,  'Oliver',   'Miller',   'oliver.m@example.com',   'Austin',        'Texas',      'USA', '2023-05-19'),
    (4,  'Sophia',   'Moore',    'sophia.m@example.com',   'New York',      'New York',   'USA', '2023-07-02'),
    (5,  'James',    'Taylor',   'james.t@example.com',    'Seattle',       'Washington', 'USA', '2023-08-24'),
    (6,  'Ava',      'Anderson', 'ava.a@example.com',      'San Francisco', 'California', 'USA', '2023-10-15'),
    (7,  'William',  'Thomas',   'william.t@example.com',  'Houston',       'Texas',      'USA', '2024-01-20'),
    (8,  'Mia',      'Jackson',  'mia.j@example.com',      'Miami',         'Florida',    'USA', '2024-02-11'),
    (9,  'Benjamin', 'Martin',   'ben.m@example.com',      'Chicago',       'Illinois',   'USA', '2024-04-03'),
    (10, 'Charlotte','Lee',      'charlotte.l@example.com','Sacramento',    'California', 'USA', '2024-06-29'),
    (11, 'Lucas',    'Perez',    'lucas.p@example.com',    'Denver',        'Colorado',   'USA', '2024-09-14'),
    (12, 'Amelia',   'White',    'amelia.w@example.com',   'Boston',        'Massachusetts','USA','2025-01-05');

INSERT INTO Products (ProductID, Name, Category, UnitPrice, StockQuantity) VALUES
    (1, 'Laptop Pro 14',        'Electronics',  1899.00,  40),
    (2, 'Wireless Mouse',       'Accessories',    29.99, 500),
    (3, 'Mechanical Keyboard',  'Accessories',   119.00, 200),
    (4, '27" 4K Monitor',       'Electronics',   449.00,  75),
    (5, 'USB-C Hub',            'Accessories',    59.00, 300),
    (6, 'Noise-Cancel Headset', 'Audio',         249.00, 120),
    (7, 'Standing Desk',        'Furniture',     599.00,  30),
    (8, 'Ergonomic Chair',      'Furniture',     399.00,  45),
    (9, 'HD Webcam',            'Electronics',    89.00,  60);  -- never ordered

INSERT INTO Orders (OrderID, CustomerID, EmployeeID, OrderDate, Status, TotalAmount) VALUES
    (1,  1,  9,  '2024-01-15', 'Delivered', 1928.99),
    (2,  2,  9,  '2024-02-03', 'Delivered',  568.00),
    (3,  3,  10, '2024-03-22', 'Delivered',  119.00),
    (4,  4,  9,  '2024-04-10', 'Cancelled',  449.00),
    (5,  6,  10, '2024-05-18', 'Delivered', 2348.00),
    (6,  1,  10, '2024-07-01', 'Delivered',  249.00),
    (7,  7,  9,  '2024-08-09', 'Shipped',    998.00),
    (8,  8,  15, '2024-10-30', 'Delivered',   88.99),
    (9,  10, 10, '2024-12-12', 'Delivered', 1899.00),
    (10, 5,  15, '2025-01-20', 'Shipped',    508.00),
    (11, 9,  9,  '2025-02-14', 'Pending',    399.00),
    (12, 2,  15, '2025-03-03', 'Pending',    177.98);

INSERT INTO OrderItems (OrderItemID, OrderID, ProductID, Quantity, UnitPrice) VALUES
    (1,  1,  1, 1, 1899.00), (2,  1,  2, 1,  29.99),
    (3,  2,  4, 1,  449.00), (4,  2,  3, 1, 119.00),
    (5,  3,  3, 1,  119.00),
    (6,  4,  4, 1,  449.00),
    (7,  5,  1, 1, 1899.00), (8,  5,  4, 1, 449.00),
    (9,  6,  6, 1,  249.00),
    (10, 7,  7, 1,  599.00), (11, 7,  8, 1, 399.00),
    (12, 8,  2, 1,   29.99), (13, 8,  5, 1,  59.00),
    (14, 9,  1, 1, 1899.00),
    (15, 10, 4, 1,  449.00), (16, 10, 5, 1,  59.00),
    (17, 11, 8, 1,  399.00),
    (18, 12, 5, 2,   59.00), (19, 12, 2, 2,  29.99);
