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


readFile("blogdata.txt")