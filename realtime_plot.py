import time
import matplotlib.pyplot as plt
import numpy as np
import math

plt.ion()

tstart = time.time()               # for profiling
x = np.arange(0,2*math.pi,0.0001)            # x-array
line, = plt.plot(x,np.sin(x))
plt.show()
for i in np.arange(1,200):
    line.set_ydata(np.sin(x+i/10.0))  # update the data
    plt.draw()                         # redraw the canvas
    plt.pause(.1)
    print "\a"

print 'FPS:' , 200/(time.time()-tstart)