import re,subprocess,sys,collections
out=subprocess.run(["npx","tsc","--noEmit","-p","."],capture_output=True,text=True).stdout
fixes=collections.defaultdict(list)
for m in re.finditer(r"^(\S+)\((\d+),(\d+)\): error TS(2339|2353): (?:Property|Object literal may only specify known properties, and) 'flow'",out,re.M):
    fixes[m[1]].append((int(m[2]),int(m[3])))
n=0
for f,locs in fixes.items():
    L=open(f).read().split('\n')
    for ln,col in sorted(set(locs),reverse=True):
        s=L[ln-1]
        if s[col-1:col+3]=="flow":
            L[ln-1]=s[:col-1]+"machine"+s[col+3:];n+=1
    open(f,'w').write('\n'.join(L))
print("fixed",n)
