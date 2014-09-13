library(ggplot2)
crDf = read.csv("sfCrime.csv", header=TRUE, fill=TRUE)
# Exploratory Data Analysis
summary(crDf)
head(crDf)
names(crDf)
nrow(crDf)

# WHERE SHOULDN'T YOU PARK YOUR CAR?
uniDescription = crDf[!duplicated(crDf["Descript"]),"Descript"]

# From the uniDescription, we get a sense of the description which tells us where we should not park cars. 
# We find the words AUTO and VEHICLE which indicates crimes related to cars. We should target these places not to park cars.

toMatch = c("AUTO", "VEHICLE")
add = crDf[grep(paste(toMatch, collapse="|"), crDf[,"Descript"]),c("Address")]
df = as.data.frame(table(add))
df$rank = rank(-df$Freq,ties.method="min")
df = df[order(df$rank,decreasing = F),]

# Top 10 addresses where most of the AUTO/VEHICLE related thefts have happened
df[1:10,]

# Bar plot showing the same
q = qplot(x=add, y=Freq, data=df[1:10,], geom="bar", stat="identity")
q + theme(axis.text.x = element_text(angle = 90, hjust = 1))

# WHAT ARE THE SAFEST LOCATIONS IN SF?
safeAdd = crDf[,"Address"]
safeDf = as.data.frame(table(safeAdd))
safeDf$rank = rank(-safeDf$Freq,ties.method="min")
safeDf = safeDf[order(safeDf$rank,decreasing = T),]

### WHAT DAY/TIMES ARE ESPECIALLY DANGEROUS?
dangerousDay = crDf[,c("DayOfWeek")]
dangDf = as.data.frame(table(dangerousDay))
dangDf$rankDay = rank(-dangDf$Freq, ties.method="min")
dangDf = dangDf[order(dangDf$rank, decreasing=F),]

### ARE CERTAIN THEFTS MORE COMMON IN CERTAIN AREAS?
toMatch = c("THEFT")
add = crDf[grep(paste(toMatch, collapse="|"), crDf[,"Descript"]),c("Address","Descript") ]
add$Count = 1
library(data.table)
dtAdd = data.table(add)
dtAdd[,Freq:=sum(Count), by=list(Address, Descript)]
dfAdd = as.data.frame(dtAdd)
theftGroupByCat = unique(dfAdd[,!names(dfAdd) %in% c("Count")])
aggData = aggregate(theftGroupByCat$Freq, by=list(theftGroupByCat$Descript), FUN=max, na.rm=TRUE)
nrow(aggData)
head(aggData)
