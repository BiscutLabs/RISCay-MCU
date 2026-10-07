ThisBuild / scalaVersion := "2.13.18"
ThisBuild / organization := "io.github.biscutlabs"
ThisBuild / version := "0.1.0-SNAPSHOT"

lazy val settings = Seq(
  libraryDependencies ++= Seq(
    "io.github.biscutlabs" %% "chisel-async" % "0.1.0-RC1",
    "org.scalatest" %% "scalatest" % "3.2.20" % Test
  ),
  addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % "7.16.0" cross CrossVersion.full),
  scalacOptions ++= Seq("-deprecation", "-feature", "-unchecked", "-Ymacro-annotations", "-language:reflectiveCalls"),
  Test / parallelExecution := false,
  publish / skip := true
)
lazy val shared = project.in(file("shared")).settings(settings)
lazy val soc = project.in(file("soc")).dependsOn(shared).settings(settings)
lazy val profiles = project.in(file("profiles")).dependsOn(soc).settings(settings)
lazy val fourPhaseBd = project.in(file("designs/four-phase-bd")).dependsOn(profiles).settings(settings)
lazy val twoPhaseClick = project.in(file("designs/two-phase-click")).dependsOn(profiles).settings(settings)
lazy val verification = project.in(file("verification")).dependsOn(fourPhaseBd, twoPhaseClick, profiles).settings(settings)
lazy val root = project.in(file(".")).aggregate(shared, soc, profiles, fourPhaseBd, twoPhaseClick, verification).settings(
  publish / skip := true,
  Compile / sources := Seq.empty
)
