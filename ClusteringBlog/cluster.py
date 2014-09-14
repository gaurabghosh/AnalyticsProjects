from math import sqrt

def readFile(filename):
	lines = [line for line in file(filename)]

	colnames = lines[0].split("\t")[1:]
	data = []
	rownames = []
	for line in lines[1:]:
		line = line.strip()
		p = line.split("\t")
		rownames.append(p[0])
		data.append([float(x) for x in p[1:]])
	return colnames, rownames, data

def pearson(x, y):
	print 2**2
	meanx = sum(x)/len(x)
	meany = sum(y)/len(y)
	sumx = 0.0
	sumy = 0.0
	sumxy = 0.0
	for i in x:
		sumx += (i - meanx)**2
	for j in y:
		sumy += (j - meany)**2
	for index, val in enumerate(x):
		sumxy += (x[index] - meanx)*(y[index] - meany)
	r = sumxy/(sqrt(sumx)*sqrt(sumy))

	return r

#readFile("blogdata.txt")
print pearson([1,2,3], [6,4,1])