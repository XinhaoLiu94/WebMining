import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import sqlite3
import re
import searchengine

ignoreWords = {'the': 1, 'of': 1, 'to': 1, 'and': 1, 'a': 1, 'in': 1, 'is': 1, 'it': 1}


class crawler:
    #初始化crawler类并传入数据库名称
    def __init__(self,dbname):
        self.con = sqlite3.connect(dbname)

    def __del__(self):
        self.con.close()


    def dbcommit(self):
        self.con.commit()

    #辅助函数，用于获取条目的id，如果条目不存在，就将其加入数据库中
    def getEntryId(self,table,field,value,createnew=True):
        cur = self.con.execute("select rowid from %s where %s='%s'" % (table, field, value))
        res = cur.fetchone()
        if res is None:
            cur = self.con.execute("insert into %s (%s) values ('%s')" % (table, field, value))
            return cur.lastrowid
        else:
            return res[0]

    #为每个网页建立索引
    def addToIndex(self,url,soup):
        if self.isIndexed(url):return
        print('Indexing ' + url)

        #获取每个单词
        text = self.getTextOnly(soup)
        words = self.seperateWords(text)

        #得到URL的id
        urlid = self.getEntryId('urllist','url',url)

        #将每个单词与该url关联
        for i in range(len(words)):
            word = words[i]
            if word in ignoreWords:
                continue
            wordid = self.getEntryId('wordlist','word',word)
            self.con.execute("insert into wordlocation(urlid,wordid,location) values (%d,%d,%d)" % (urlid, wordid, i))

    #从一个HTML网页中提取文字（不带标签的）
    def getTextOnly(self,soup):
        v = soup.string
        if v == None:
            c = soup.contents
            resulttext = ''
            for t in c:
                subtext = self.getTextOnly(t)
                resulttext += subtext + '\n'
            return resulttext
        else:
            return v.strip()

    #根据任何非空白字符进行分词处理
    def seperateWords(self,text):
        splitter = re.compile('\\W*')
        return [s.lower() for s in splitter.split(text) if s != '']

    #如果url已经建立过索引，则返回true
    def isIndexed(self,url):
        u = self.con.execute("select rowid from urllist where url = '%s'" % url).fetchone()
        if u != None:
            #检查他是否已经被检索过了
            v = self.con.execute('select * from wordlocation where urlid = %d' % u[0]).fetchone()
            if v != None:
                return True

        return False

    #添加一个关联两个网页的链接
    def addLinkRef(self,urlFrom,urlTo,linkText):
        pass

    #从一小组网页开始进行广度优先搜索，直至某一给定深度，
    #期间为网页建立索引
    def crawl(self,pages,depth = 2):
        for i in range(depth):
            newPages = {}
            for page in pages:
                try:
                    c = urllib.request.urlopen(page)
                except:
                    print("Could not open %s" % page)
                    continue
                try:
                    soup = BeautifulSoup(c.read())
                    self.addToIndex(page,soup)

                    links = soup('a')
                    for link in links:
                        if 'href' in dict(link.attrs):
                            url = urllib.request.urljoin(page,link['href'])
                            if url.find("'") != -1:
                                continue
                            url = url.split('#')[0]
                            if url[0:4] == 'http' and not self.isIndexed(url):
                                newPages[url] = 1
                            linkText = self.getTextOnly(link)
                            self.addLinkRef(page,url,linkText)

                    self.dbcommit()

                except:

                    print("Could not parse page %s" % page)

            pages = newPages


    #创建数据库表
    def createIndexTables(self):
        self.con.execute('create table urllist(url)')
        self.con.execute('create table wordlist(word)')
        self.con.execute('create table wordlocation(urlid,wordid,location)')
        self.con.execute('create table link(fromid integer,toid integer)')
        self.con.execute('create table linkwords(wordid,linkid)')
        self.con.execute('create index wordidx on wordlist(word)')
        self.con.execute('create index urlidx on urllist(url)')
        self.con.execute('create index wordurlidx on wordlocation(wordid)')
        self.con.execute('create index urltoidx on link(toid)')
        self.con.execute('create index urlfromidx on link(fromid)')
        self.dbcommit()

    class searcher:
        def __init__(self,dbname):
            self.con = sqlite3.connect(dbname)

        def __del__(self):
            self.con.close()

        def getMatchRows(self,q):
            #构造查询的字符串
            fieldlist = 'w0.urlid'
            tablelist = ''
            clauselist = ''
            wordids = []

            #根据空格拆分单词
            words = q.split(' ')
            tablenumber = 0

            for word in words:
                wordrow = self.con.execute("select rowid from wordlist where word='%s'" % word).fetchone()
                if wordrow is not None:
                    wordid = wordrow[0]
                    wordids.append(wordid)
                    if tablenumber > 0:
                        tablelist += ','
                        clauselist += ' and '
                        clauselist += 'w%d.urlid=w%d.urlid and ' % (tablenumber - 1, tablenumber)
                    fieldlist += ',w%d.location' % tablenumber
                    tablelist += 'wordlocation w%d' % tablenumber
                    clauselist += 'w%d.wordid=%d' % (tablenumber, wordid)
                    tablenumber += 1

            #根据各个组分，建立查询
            fullquery = 'select %s from %s where %s' % (fieldlist, tablelist, clauselist)
            print(fullquery)
            cur = self.con.execute(fullquery)
            rows = [row for row in cur]

            return rows, wordids

        def getScoredList(self, rows, wordids):
            totalScores = dict([(row[0],0) for row in rows])

            #这里是稍后放置评价函数的地方
            weights = [(1.0, self.frequencyScore(rows))]

            for (weight, scores) in weights:
                for url in totalScores:
                    totalScores[url] += weight * scores[url]
            return  totalScores

        def geturlname(self,id):
            return self.con.execute("select url from urllist where rowid = %d" % id).fetchone()[0]

        def query(self, q):
            rows, wordids = self.getMatchRows(q)
            scores = self.getScoredList(rows, wordids)
            rankedScores = [(score, url) for (url, score) in scores.items()]
            rankedScores.sort()
            rankedScores.reverse()
            for (score, urlid) in rankedScores[0:10]:
                print('%f\t%s' % (score, self.geturlname(urlid)))
            return wordids, [r[1] for r in rankedScores[0:10]]

        def normalizeScores(self, scores, smallIsBetter = 0):
            vsmall = 0.00001
            if smallIsBetter:
                minScore = min(scores.values())
                return dict([(u,float(minScore) / max(vsmall, l)) for (u, l) in scores.items()])
            else:
                maxScore = max(scores.values())
                if maxScore == 0:
                    maxScore = vsmall
                return dict([(u, float(c) / maxScore) for (u, c) in scores.items()])

        def frequencyScore(self, rows):
            counts = dict([(row[0],0) for row in rows])
            for row in rows:
                counts[row[0]] += 1
            return self.normalizeScores(counts)



    if __name__ == '__main__':
        e = searcher('searchindex.db')
        e.query('wikipedia kingdom')


