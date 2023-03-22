FROM docker.elastic.co/elasticsearch/elasticsearch:7.10.2

RUN ./bin/elasticsearch-plugin install org.wikimedia.search.highlighter:experimental-highlighter-elasticsearch-plugin:7.10.2
