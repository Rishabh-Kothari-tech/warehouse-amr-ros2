# A named warehouse location in the map frame.
string name
string type          # shelf | packing | charger | home
float64 x
float64 y
float64 yaw          # radians, map frame
string[] items       # SKUs stocked at this station (shelves only)
