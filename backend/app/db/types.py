from sqlalchemy import Numeric

Money = Numeric(18, 4, asdecimal=True)
UnitCost = Numeric(18, 6, asdecimal=True)
Quantity = Numeric(20, 6, asdecimal=True)
Rate = Numeric(9, 6, asdecimal=True)
