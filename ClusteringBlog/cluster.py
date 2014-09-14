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
	if (sumx*sumy) != 0:
		r = sumxy/(sqrt(sumx)*sqrt(sumy))
	else:
		r= 0.0
	return 1 - r

class bicluster:
	def __init__(self, vec, left=None, right=None, distance=0.0, id=None):
		self.left = left
		self.right = right
		self.distance = distance
		self.id = id
		self.vec = vec

def hcluster(rows,distance=pearson):
	distances={}
 	currentclustid=-1
 	# Clusters are initially just the rows (i.e, the blogs with the word occurences vector)
 	clust=[bicluster(rows[i],id=i) for i in range(len(rows))]
 	while len(clust)>1:
 		lowestpair=(0,1)
 		closest=distance(clust[0].vec,clust[1].vec)
		 # loop through every pair looking for the smallest distance
 		for i in range(len(clust)):
 			for j in range(i+1,len(clust)):
			 # distances is the cache of distance calculations
 				if (clust[i].id,clust[j].id) not in distances:
 					distances[(clust[i].id,clust[j].id)]=distance(clust[i].vec,clust[j].vec)
 				d=distances[(clust[i].id,clust[j].id)]
 			if d<closest:
 				closest=d
 				lowestpair=(i,j)
 	# calculate the average of the two clusters
 	mergevec=[(clust[lowestpair[0]].vec[i]+clust[lowestpair[1]].vec[i])/2.0 for i in range(len(clust[0].vec))]
 	# create the new cluster
 	newcluster=bicluster(mergevec,left=clust[lowestpair[0]], right=clust[lowestpair[1]], distance=closest,id=currentclustid)
 	# cluster ids that weren't in the original set are negative
 	currentclustid-=1
 	del clust[lowestpair[1]]
 	del clust[lowestpair[0]]
 	clust.append(newcluster)
 	return clust[0]

blognames, words, data = readFile("blogdata.txt")
clust = hcluster(data)

print clust