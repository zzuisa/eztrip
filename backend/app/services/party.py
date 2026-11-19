"""Explicit party, room and vehicle units shared by pricing and budget code."""
import math

def positive_int(value, default=1, limit=20):
    try: return max(1,min(limit,int(value)))
    except (ValueError,TypeError,OverflowError): return default

def counts(meta):
    n=positive_int(meta.get('travelers'))
    rooms=min(n,positive_int(meta.get('rooms'),math.ceil(n/2)))
    driving=bool(meta.get('rental')) or any(s in str(meta.get('transportation') or '') for s in ('自驾','开车','租车','驾车'))
    vehicles=max(math.ceil(n/5),positive_int(meta.get('vehicle_count'),math.ceil(n/5))) if driving else 0
    return {'travelers':n,'rooms':rooms,'adults':n,'room_distribution':[n//rooms+(i<n%rooms) for i in range(rooms)],
            'vehicles':vehicles,'vehicle_seats':5,'taxi_vehicles':math.ceil(n/4),
            'rooms_assumed':not bool(meta.get('rooms')),'vehicles_assumed':driving and not bool(meta.get('vehicle_count'))}
