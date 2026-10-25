import re,subprocess,collections
out=subprocess.run(["npx","tsc","--noEmit","-p","."],capture_output=True,text=True).stdout
locs=collections.defaultdict(set)
for m in re.finditer(r"^(\S+)\((\d+),(\d+)\): error TS(?:2741|2322|2345): .*?(?:Property 'machine' is missing|flow)",out,re.MULTILINE):
    locs[m[1]].add(int(m[2]))
n=0
for f,lines in locs.items():
    L=open(f).read().split('\n')
    for ln in sorted(lines):
        for k in range(ln-1,min(ln+3,len(L))):
            s=L[k]
            t=re.sub(r"\bflow:(?= )","machine:",s,count=1)
            if t==s: t=re.sub(r"([{,] )flow( [,}])",r"\1machine: flow\2",s,count=1)
            if t!=s: L[k]=t;n+=1;break
    open(f,'w').write('\n'.join(L))
print("fixed",n)
