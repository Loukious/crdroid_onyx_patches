// Scoped APK60715 bir metadata overlay. Never modifies the compressed flagset or tokens.
#include "snapshot-contract.h"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/xattr.h>
#include <unistd.h>
#include <vector>

using Bytes = std::vector<uint8_t>;
static const std::string kInfo = "/data/user/0/com.google.android.mosey/files/phenotype_storage_info/shared/storage-info.pb";
static const std::string kNamespace = "mosey_app_android#com.google.android.mosey";
static const std::string kBool = "45768305", kCountry = "45718707";
static void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static Bytes bytes(const std::string& s) { return Bytes(s.begin(), s.end()); }
static std::string text(const Bytes& b) { return std::string(b.begin(), b.end()); }
static void append(Bytes& out, const Bytes& b) { out.insert(out.end(), b.begin(), b.end()); }
static uint64_t varint(const Bytes& b, size_t& p) {
  uint64_t v=0; unsigned shift=0;
  for (unsigned n=0;n<10;n++,shift+=7) {
    require(p<b.size(), "truncated varint"); uint8_t c=b[p++];
    require(n!=9 || c<2, "overflow varint"); v |= uint64_t(c&127)<<shift;
    if (!(c&128)) return v;
  }
  throw std::runtime_error("overflow varint");
}
static Bytes vi(uint64_t v) { Bytes b; do { b.push_back(uint8_t(v&127)|(v>=128?128:0)); v>>=7; } while(v); return b; }
struct Field { unsigned n,w; uint64_t v=0; Bytes raw,data; };
static std::vector<Field> parse(const Bytes& b) {
  require(b.size()<=8*1024*1024, "protobuf too large"); std::vector<Field> out; size_t p=0;
  while(p<b.size()) {
    require(out.size()<8192, "too many protobuf fields"); size_t start=p; uint64_t tag=varint(b,p);
    require((tag>>3)>0 && (tag>>3)<=0x1fffffff, "invalid protobuf tag");
    Field f{unsigned(tag>>3),unsigned(tag&7),0,{}, {}};
    if (f.w==0) f.v=varint(b,p);
    else {
      size_t length=f.w==1?8:f.w==5?4:f.w==2?size_t(varint(b,p)):0;
      require(f.w==1 || f.w==2 || f.w==5, "unsupported protobuf wire type");
      require(length<=b.size()-p, "truncated protobuf field"); f.data=Bytes(b.begin()+p,b.begin()+p+length); p+=length;
    }
    f.raw=Bytes(b.begin()+start,b.begin()+p); out.push_back(std::move(f));
  }
  return out;
}
static Bytes ld(unsigned n,const Bytes& data) { Bytes b=vi((uint64_t(n)<<3)|2); append(b,vi(data.size()));append(b,data);return b; }
static Bytes scalar(unsigned n,uint64_t v) { Bytes b=vi(uint64_t(n)<<3);append(b,vi(v));return b; }
static const Field* single(const std::vector<Field>& fs,unsigned n,unsigned w,bool needed=true) {
  const Field* result=nullptr;
  for(const auto& f:fs) if(f.n==n) { require(!result && f.w==w,"duplicate/wrong schema field");result=&f; }
  require(result || !needed,"missing schema field");return result;
}
static uint32_t r32(const Bytes& b,size_t p) { require(p+4<=b.size(),"truncated header");return uint32_t(b[p])|uint32_t(b[p+1])<<8|uint32_t(b[p+2])<<16|uint32_t(b[p+3])<<24; }
static uint32_t rotate(uint32_t x,unsigned n) { return x>>n|x<<(32-n); }
static std::string sha(const Bytes& input) {
  static const uint32_t k[]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
  std::array<uint32_t,8> h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  Bytes b=input;uint64_t bits=uint64_t(b.size())*8;b.push_back(128);while(b.size()%64!=56)b.push_back(0);for(int i=7;i>=0;i--)b.push_back(uint8_t(bits>>(i*8)));
  for(size_t p=0;p<b.size();p+=64) {
    uint32_t w[64];for(unsigned i=0;i<16;i++)w[i]=uint32_t(b[p+i*4])<<24|uint32_t(b[p+i*4+1])<<16|uint32_t(b[p+i*4+2])<<8|b[p+i*4+3];
    for(unsigned i=16;i<64;i++){uint32_t x=w[i-15],y=w[i-2];w[i]=w[i-16]+(rotate(x,7)^rotate(x,18)^(x>>3))+w[i-7]+(rotate(y,17)^rotate(y,19)^(y>>10));}
    auto v=h;for(unsigned i=0;i<64;i++){uint32_t t1=v[7]+(rotate(v[4],6)^rotate(v[4],11)^rotate(v[4],25))+((v[4]&v[5])^(~v[4]&v[6]))+k[i]+w[i];uint32_t t2=(rotate(v[0],2)^rotate(v[0],13)^rotate(v[0],22))+((v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]));for(unsigned j=7;j>0;j--)v[j]=v[j-1];v[4]+=t1;v[0]=t1+t2;}for(unsigned i=0;i<8;i++)h[i]+=v[i];
  }
  std::ostringstream s;s<<std::hex<<std::setfill('0');for(auto x:h)s<<std::setw(8)<<x;return s.str();
}
static Bytes unhex(const char* h) { Bytes b;size_t n=std::strlen(h);require(n%2==0,"invalid compiled map");for(size_t i=0;i<n;i+=2)b.push_back(uint8_t(std::stoul(std::string(h+i,2),nullptr,16)));return b; }
static uint64_t rol64(uint64_t x,unsigned n){return x<<n|x>>(64-n);}
static uint64_t r64(const Bytes& b,size_t p,size_t n=8){uint64_t v=0;for(size_t i=0;i<n;i++)v|=uint64_t(b[p+i])<<(8*i);return v;}
static Bytes murmur(const Bytes& b) {
  uint64_t a=0,c=0,c1=0x87c37b91114253d5ULL,c2=0x4cf5ad432745937fULL;size_t p=0;
  for(;p+16<=b.size();p+=16){a^=rol64(r64(b,p)*c1,31)*c2;a=(rol64(a,27)+c)*5+0x52dce729;c^=rol64(r64(b,p+8)*c2,33)*c1;c=(rol64(c,31)+a)*5+0x38495ab5;}
  size_t tail=b.size()-p;if(tail>8)c^=rol64(r64(b,p+8,tail-8)*c2,33)*c1;if(tail)a^=rol64(r64(b,p,std::min(tail,size_t(8)))*c1,31)*c2;
  a^=b.size();c^=b.size();a+=c;c+=a;auto mix=[](uint64_t x){x^=x>>33;x*=0xff51afd7ed558ccdULL;x^=x>>33;x*=0xc4ceb9fe1a85ec53ULL;return x^(x>>33);};a=mix(a);c=mix(c);a+=c;c+=a;Bytes out;for(auto x:{a,c})for(unsigned i=0;i<8;i++)out.push_back(uint8_t(x>>(8*i)));return out;
}
static std::string b64(const Bytes& b){static const char* alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";std::string s;for(size_t p=0;p<b.size();p+=3){uint32_t x=uint32_t(b[p])<<16;if(p+1<b.size())x|=uint32_t(b[p+1])<<8;if(p+2<b.size())x|=b[p+2];s+=alphabet[x>>18];s+=alphabet[(x>>12)&63];s+=p+1<b.size()?alphabet[(x>>6)&63]:'=';s+=p+2<b.size()?alphabet[x&63]:'=';}return s;}

struct File { Bytes data,label;struct stat st{}; };
static File readFile(const std::string& path) {
  int fd=open(path.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);require(fd>=0,"cannot open regular source file");File f;
  try {require(fstat(fd,&f.st)==0 && S_ISREG(f.st.st_mode),"source is not regular");require(f.st.st_size>=0 && f.st.st_size<=8*1024*1024,"source size rejected");f.data.resize(size_t(f.st.st_size));size_t p=0;while(p<f.data.size()){ssize_t n=read(fd,f.data.data()+p,f.data.size()-p);require(n>0,"short source read");p+=size_t(n);}struct stat after{};require(fstat(fd,&after)==0 && after.st_size==f.st.st_size && after.st_mtim.tv_sec==f.st.st_mtim.tv_sec && after.st_mtim.tv_nsec==f.st.st_mtim.tv_nsec && after.st_ctim.tv_sec==f.st.st_ctim.tv_sec && after.st_ctim.tv_nsec==f.st.st_ctim.tv_nsec,"source changed during read");ssize_t len=fgetxattr(fd,"security.selinux",nullptr,0);if(len>0){f.label.resize(size_t(len));require(fgetxattr(fd,"security.selinux",f.label.data(),f.label.size())==len,"cannot read source label");}
#ifndef MOSEY_CACHE_HOST_TEST
    require(!f.label.empty(),"source SELinux label unavailable");
#endif
  } catch(...) {close(fd);throw;}close(fd);return f;
}
static bool exists(const std::string& p){struct stat st{};return lstat(p.c_str(),&st)==0;}
static File readPrivate(const std::string& p){File f=readFile(p);require(f.st.st_uid==getuid() && (f.st.st_mode&07777)==0600 && f.st.st_nlink==1,"baseline is not private/owned");return f;}
static bool same(const File& a,const File& b){return a.st.st_dev==b.st.st_dev && a.st.st_ino==b.st.st_ino && a.st.st_uid==b.st.st_uid && a.st.st_gid==b.st.st_gid && a.st.st_mode==b.st.st_mode && a.st.st_ctim.tv_sec==b.st.st_ctim.tv_sec && a.st.st_ctim.tv_nsec==b.st.st_ctim.tv_nsec && a.st.st_mtim.tv_sec==b.st.st_mtim.tv_sec && a.st.st_mtim.tv_nsec==b.st.st_mtim.tv_nsec && a.label==b.label && a.data==b.data;}
static void writeAll(int fd,const Bytes& b){size_t p=0;while(p<b.size()){ssize_t n=write(fd,b.data()+p,b.size()-p);require(n>0,"short output write");p+=size_t(n);}require(fsync(fd)==0,"cannot sync output");}
static std::string parent(const std::string& p){return p.substr(0,p.rfind('/'));}
static void syncDir(const std::string& p){int fd=open(p.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);require(fd>=0,"cannot open output directory");int result=fsync(fd);close(fd);require(result==0,"cannot sync output directory");}
static void once(const std::string& p,const Bytes& b){int fd=open(p.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);require(fd>=0,"baseline already exists or unavailable");try{writeAll(fd,b);}catch(...){close(fd);throw;}close(fd);syncDir(parent(p));}
#ifdef MOSEY_CACHE_HOST_TEST
// Deterministic test barrier; absent from production builds.
static void beforeRecheck(){const char* dir=std::getenv("MOSEY_CACHE_TEST_SYNC_DIR");if(!dir)return;std::string root=dir;once(root+"/ready",{});for(unsigned i=0;i<1000;i++){if(exists(root+"/continue"))return;usleep(10000);}throw std::runtime_error("test barrier timed out");}
#endif
static void replace(const std::string& p,const File& original,const Bytes& data) {
  std::string pattern=parent(p)+"/.onyx-mosey-cache-XXXXXX";std::vector<char> name(pattern.begin(),pattern.end());name.push_back(0);int fd=mkstemp(name.data());require(fd>=0,"cannot create atomic output");std::string temp=name.data();
  try {require(fchown(fd,original.st.st_uid,original.st.st_gid)==0 && fchmod(fd,original.st.st_mode&07777)==0,"cannot preserve ownership/mode");if(!original.label.empty())require(fsetxattr(fd,"security.selinux",original.label.data(),original.label.size(),0)==0,"cannot preserve SELinux label");writeAll(fd,data);require(close(fd)==0,"cannot close atomic output");fd=-1;
#ifdef MOSEY_CACHE_HOST_TEST
    beforeRecheck();
#endif
    require(same(original,readFile(p)),"source changed before replacement");require(rename(temp.c_str(),p.c_str())==0,"cannot atomically replace source");syncDir(parent(p));File published=readFile(p);require(published.data==data && published.st.st_uid==original.st.st_uid && published.st.st_gid==original.st.st_gid && (published.st.st_mode&07777)==(original.st.st_mode&07777) && published.label==original.label,"published file identity changed immediately");}
  catch(...){if(fd>=0)close(fd);unlink(temp.c_str());throw;}
}
struct Entry { std::string key;std::vector<Field> fields,value;Bytes raw; };
static Entry entry(const Field& f){Entry e;e.raw=f.raw;e.fields=parse(f.data);e.key=text(single(e.fields,1,2)->data);require(!e.key.empty(),"empty override map key");e.value=parse(single(e.fields,2,2)->data);const Field* name=single(e.value,10,2,false);if(e.key==kBool || e.key==kCountry)require(name && text(name->data)==e.key,"managed bin name mismatch");else if(name)require(text(name->data)!=kBool && text(name->data)!=kCountry,"managed bin name alias");return e;}
struct Snapshot { Bytes header,suffix,compressed,metadata;std::vector<Field> fields;std::map<std::string,Entry> entries; };
static Snapshot snapshot(const Bytes& b){require(b.size()>=10 && r32(b,0)==1 && r32(b,4)==0,"unsupported shared snapshot header");Snapshot s;s.header=Bytes(b.begin(),b.begin()+8);size_t p=8;size_t n=size_t(varint(b,p));require(n<=65536 && n<=b.size()-p,"invalid metadata length");s.metadata=Bytes(b.begin()+p,b.begin()+p+n);p+=n;s.suffix=Bytes(b.begin()+p,b.end());size_t length=size_t(varint(b,p));require(length==b.size()-p,"truncated/trailing compressed payload");s.compressed=Bytes(b.begin()+p,b.end());bool known=false;for(const char* h:kSnapshots)known|=sha(s.compressed)==h;require(known,"unrecognized compressed flagset");s.fields=parse(s.metadata);single(s.fields,1,2);single(s.fields,2,2,false);single(s.fields,3,2);single(s.fields,4,0);for(const auto& f:s.fields)if(f.n==5){require(f.w==2,"wrong override map wire type");auto e=entry(f);require(!s.entries.count(e.key),"duplicate override map key");s.entries.emplace(e.key,std::move(e));}return s;}
static const Field& typed(const Entry& e,unsigned type,unsigned wire){const Field* result=nullptr;for(const auto& f:e.value)if(f.n>=1 && f.n<=5){require(!result && f.n==type && f.w==wire,"managed override type mismatch");result=&f;}require(result,"managed override value absent");return *result;}
static Bytes makeEntry(const Snapshot& s,const std::string& name,const Bytes& value){auto p=s.entries.find(name);Bytes bin,outer;if(p==s.entries.end()){append(bin,value);append(bin,ld(10,bytes(name)));append(outer,ld(1,bytes(name)));append(outer,ld(2,bin));}else{for(const auto& f:p->second.value)append(bin,f.n>=1&&f.n<=5?value:f.raw);for(const auto& f:p->second.fields)append(outer,f.n==2?ld(2,bin):f.raw);}return ld(5,outer);}
static Bytes rewrite(const Snapshot& s,const std::map<std::string,Bytes>& changes){Bytes meta;std::set<std::string> used;for(const auto& f:s.fields){if(f.n==5){std::string key=entry(f).key;auto p=changes.find(key);if(p!=changes.end()){append(meta,p->second);used.insert(key);continue;}}append(meta,f.raw);}for(const auto& p:changes)if(!used.count(p.first))append(meta,p.second);Bytes out=s.header;append(out,vi(meta.size()));append(out,meta);append(out,s.suffix);return out;}
static bool owned(const Entry& e,const std::string& key,const Bytes& map){if(key==kBool){const auto& f=typed(e,2,0);require(f.v<=1,"invalid Boolean override");return f.v==1;}return typed(e,5,2).data==map;}
static std::string resolve(const std::string& info){auto fs=parse(readFile(info).data);const auto* secret=single(fs,1,2);require(secret->data.size()==16,"wrong GMS shared secret length");require(single(fs,2,0)->v==1 && text(single(fs,3,2)->data)=="app_phenotype_shared","shared storage is not enabled");
  bool fileBacking=false,hasInclude=false,included=false,excluded=false;const std::string package="mosey_app_android";
  for(const auto& f:fs){if(f.n==5 || f.n==6){require(f.w==2,"wrong namespace eligibility wire type");if(f.n==5){hasInclude=true;included|=text(f.data)==package;}else excluded|=text(f.data)==package;}else if(f.n==7){require(f.w==0 || f.w==2,"wrong storage backing wire type");if(f.w==0)fileBacking|=f.v==6;else{size_t p=0;while(p<f.data.size())fileBacking|=varint(f.data,p)==6;}}}
  require(fileBacking,"FILE shared storage backing is disabled");require((!hasInclude || included) && !excluded,"Mosey namespace is not eligible for shared storage");
  auto rootFields=parse(single(fs,8,2)->data);require(single(rootFields,2,0)->v==37,"storage SDK mismatch");std::string root=text(single(rootFields,1,2)->data);require(root=="/data/user/0/com.google.android.gms" || root=="/data/data/com.google.android.gms","unsupported GMS storage root");Bytes name=bytes(kNamespace);name.push_back(0);return root+"/app_phenotype_shared/"+b64(secret->data)+"/"+b64(murmur(name))+".pb";}
// Legacy country release is separate from the new Boolean-only ownership.
static Snapshot baseline(const std::string& base,const std::string& primary) {
  require(text(readPrivate(base+"source").data)==primary &&
          text(readPrivate(base+"before.sha256").data)==sha(readPrivate(base+"before.pb").data),
          "baseline identity mismatch");
  return snapshot(readPrivate(base+"before.pb").data);
}
static void releaseCountry(const std::string& base,const std::string& primary,
                           const File& source,const Snapshot& current) {
  if(!exists(base+"before.pb")) {
    require(!exists(base+"source") && !exists(base+"before.sha256") &&
            !exists(base+"country.pb") && !exists(base+"country-released"),
            "partial legacy baseline state");
    std::cout<<"unchanged\n";return;
  }
  Snapshot original=baseline(base,primary);
  Bytes identity=readPrivate(base+"before.sha256").data;
  if(exists(base+"country-released")) {
    require(readPrivate(base+"country-released").data==identity,
            "country release marker identity mismatch");
    std::cout<<"unchanged\n";return;
  }
  Bytes map=readPrivate(base+"country.pb").data;
  bool validMap=false;
  for(const auto& c:kMaps)validMap|=map==unhex(c.desired);
  require(validMap,"invalid applied country baseline");
  std::map<std::string,Bytes> changes;
  auto now=current.entries.find(kCountry);
  auto old=original.entries.find(kCountry);
  if(old!=original.entries.end()) {
    const auto& before=typed(old->second,5,2);
    bool sameFamily=false;
    for(const auto& c:kMaps)
      sameFamily|=map==unhex(c.desired) &&
                  (before.data==unhex(c.previous) || before.data==unhex(c.desired));
    require(sameFamily,"original country family mismatch");
    require(now!=current.entries.end(),"managed country removed by another writer");
    const auto& value=typed(now->second,5,2);
    if(value.data!=before.data) {
      require(owned(now->second,kCountry,map),"managed override changed by another writer");
      changes[kCountry]=makeEntry(current,kCountry,before.raw);
    }
  } else if(now!=current.entries.end()) {
    require(owned(now->second,kCountry,map),"managed override changed by another writer");
    Snapshot empty;
    require(now->second.raw==makeEntry(empty,kCountry,ld(5,map)),
            "new owned override has unrelated changes");
    changes[kCountry]=Bytes();
  }
  Bytes output=rewrite(current,changes);
  bool changed=output!=source.data;
  if(changed)replace(primary,source,output);
  else require(same(source,readFile(primary)),"source changed before replacement");
  // A durable marker prevents future server/user country changes being rolled
  // back by the boot helper. Old files remain the untouched migration evidence.
  once(base+"country-released",identity);
  std::cout<<(changed?"changed":"unchanged")<<"\n";
}
int main(int argc,char** argv){
  try {
    std::string action,info,state,primary;
    for(int i=1;i<argc;i++){std::string a=argv[i];if(a=="--apply"||a=="--rollback"||a=="--inspect"||a=="--resolve"||a=="--release-country"){require(action.empty(),"duplicate command");action=a;}else if(a=="--storage-info"||a=="--state-dir"||a=="--primary"){require(i+1<argc,"missing option value");std::string value=argv[++i];if(a=="--storage-info")info=value;else if(a=="--state-dir")state=value;else primary=value;}else throw std::runtime_error("unknown option");}
    require(!action.empty(),"missing command");
#ifndef MOSEY_CACHE_HOST_TEST
    require(getuid()==0,"requires root");require(info==kInfo,"unsupported Mosey storage-info path");
    std::string resolved=resolve(info);require(primary.empty() || primary==resolved,"primary path mismatch");primary=resolved;
#else
    if(primary.empty())primary=resolve(info);
#endif
    if(action=="--resolve"){std::cout<<primary<<"\n";return 0;}
    require(!state.empty() && state[0]=='/',"invalid private state path");struct stat ds{};require(lstat(state.c_str(),&ds)==0 && S_ISDIR(ds.st_mode) && (ds.st_mode&07777)==0700 && ds.st_uid==getuid(),"state directory is not private/owned");
    std::string digest=sha(bytes(primary));
    std::string base=state+"/cache-overlay-bool-v10-"+digest+"-";
    int lock=open((state+"/cache-overlay-lock").c_str(),O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW,0600);struct stat ls{};require(lock>=0 && fstat(lock,&ls)==0 && S_ISREG(ls.st_mode) && (ls.st_mode&07777)==0600 && ls.st_uid==getuid() && ls.st_nlink==1 && flock(lock,LOCK_EX)==0,"cannot lock private overlay state");
    File source=readFile(primary);Snapshot current=snapshot(source.data);
    if(action=="--release-country") {
      releaseCountry(state+"/cache-overlay-"+digest+"-",primary,source,current);return 0;
    }
    if(action=="--inspect") {
      auto value=current.entries.find(kBool);
      if(value!=current.entries.end()) {
        const auto& f=typed(value->second,2,0);require(f.v<=1,"invalid Boolean override");
      }
      std::cout<<(value!=current.entries.end() && owned(value->second,kBool,{})?"true":"false")<<"\n";return 0;
    }
    std::map<std::string,Bytes> changes;
    if(action=="--apply") {
      auto b=current.entries.find(kBool);if(b!=current.entries.end()){const auto& f=typed(b->second,2,0);require(f.v<=1,"invalid Boolean override");}
      changes[kBool]=makeEntry(current,kBool,scalar(2,1));Bytes output=rewrite(current,changes);
      if(output==source.data){std::cout<<"unchanged\n";return 0;}
      if(exists(base+"before.pb"))baseline(base,primary);
      else {require(!exists(base+"source")&&!exists(base+"before.sha256"),"partial baseline state");once(base+"before.pb",source.data);once(base+"before.sha256",bytes(sha(source.data)));once(base+"source",bytes(primary));}
      replace(primary,source,output);std::cout<<"changed\n";return 0;
    }
    if(!exists(base+"before.pb")){require(!exists(base+"source")&&!exists(base+"before.sha256"),"partial baseline state");std::cout<<"unchanged\n";return 0;}
    Snapshot original=baseline(base,primary);
    auto p=current.entries.find(kBool);
    if(p!=current.entries.end()) {
      auto before=original.entries.find(kBool);
      if(before!=original.entries.end()) {
        const auto& now=typed(p->second,2,0);const auto& old=typed(before->second,2,0);
        if(now.v!=old.v) {
          require(owned(p->second,kBool,{}),"managed override changed by another writer");
          changes[kBool]=makeEntry(current,kBool,old.raw);
        }
      } else {
        require(owned(p->second,kBool,{}),"managed override changed by another writer");
        Snapshot empty;
        require(p->second.raw==makeEntry(empty,kBool,scalar(2,1)),"new owned override has unrelated changes");
        changes[kBool]=Bytes();
      }
    }
    Bytes output=rewrite(current,changes);if(output==source.data){std::cout<<"unchanged\n";return 0;}replace(primary,source,output);std::cout<<"changed\n";return 0;
  } catch(const std::exception& e){std::cerr<<"Mosey cache overlay rejected: "<<e.what()<<"\n";return 1;}
}
