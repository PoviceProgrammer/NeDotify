import sys
import traceback
sys.path.insert(0, 'c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music')
try:
    from core.app import AppCore
    print("Success")
except Exception as e:
    traceback.print_exc()
