import sbt._

/** The source receipt is also the dependency pin. Do not resolve a moving branch. */
object LibrarySource {
  def uri(pin: File): java.net.URI = {
    val json = IO.read(pin)
    def field(name: String): String = {
      val matches = ("\"" + name + "\"\\s*:\\s*\"([^\"]+)\"").r.findAllMatchIn(json).toList
      require(matches.size == 1, s"Expected one $name in $pin")
      matches.head.group(1)
    }
    val repository = field("repository")
    val commit = field("commit")
    require(repository == "https://github.com/BiscutLabs/chisel-async", "Unexpected library repository")
    require(commit.matches("[0-9a-f]{40}"), "Library dependency requires a full Git commit")
    new java.net.URI(s"$repository.git#$commit")
  }
}
